import os
import sys
import json
import re
import pytz
from datetime import datetime
from time import sleep
from logging import getLogger
import base64
import asyncio
from fastapi import WebSocket
from openai import AsyncOpenAI
from openai_api.models import ChatPrompt
from chat_wb.voice.text2voice import playVoicePeak
from chat_wb.neo4j.triplet import TripletsConverter
from chat_wb.neo4j.neo4j import get_node, get_node_relationships_between, get_node_relationships
from chat_wb.neo4j.memory import query_messages, get_messages, get_message_entities
from chat_wb.models import Triplets, WebSocketInputData, ShortMemory, remove_suffix, MessageNode
logger = getLogger(__name__)


# 音声合成して、wavファイルのfilepathを返す
async def get_voice(text: str, narrator: str = "Asumi Ririse"):
    file_path = await playVoicePeak(script=text, narrator=narrator)

    if not file_path:
        return {
            "status": "queued",
            "message": "Your request is queued. Please check back later.",
        }
    return file_path


# StreamChatClientを管理する辞書
stream_chat_clients = {}


async def get_stream_chat_client(input_data: WebSocketInputData):
    title = input_data.title
    if title not in stream_chat_clients:
        stream_chat_clients[title] = StreamChatClient(input_data)
        # 初期化時に、character_settings, short_memoryの読み込みを行う。
        await stream_chat_clients[title].init()
    else:
        stream_chat_clients[title].set_user_input(input_data.user_input)
    return stream_chat_clients[title]


# AIの会話応答を行うするクラス
class StreamChatClient():
    def __init__(self, input_data: WebSocketInputData) -> None:
        self.time_zone = "Asia/Tokyo"   # [TODO] User Setting
        self.current_time = datetime.now(pytz.timezone(self.time_zone)).strftime("%Y-%m-%d %H:%M:%S")
        self.location = "Yokohama"      # [TODO] User node properties and AI node properties
        self.user = input_data.user
        self.AI = input_data.AI
        self.character_settings: Triplets
        self.character_name_lsit: list[str] | None = None   # user, AIのname_variationを含めたname_list
        self.title = input_data.title
        self.latest_message_id: int | None = None   # store_messageで、former_node_idを指定するために使用
        self.client = AsyncOpenAI()
        self.user_input: str = input_data.user_input
        self.user_input_type: str | None = None  # 不要なTripletsを保存しないための分類（code, documents, chat, question）
        self.user_input_entity: Triplets | None = None  # ユーザー入力から抽出したTriplets
        self.ai_response: str | None = None   # ai_responseの一時保存
        self.retrieved_memory: Triplets | None = None  # neo4jから取得した情報の一時保存
        self.short_memory: ShortMemory  # チャットとlong_memoryの履歴、memoryを最大7個まで格納する
        self.short_memory_limit = 7     # [TODO] User Setting
        self.short_memory_depth = 1     # [TODO] User Setting
        self.short_memory_input_size = 4096  # [TODO] User Setting

    async def init(self):
        # load character_settings
        # user, AIのノード、両者間のリレーションシップを取得する。
        label = "Person"
        AI, user, relationships = await asyncio.gather(
            get_node(label, self.AI),
            get_node(label, self.user),
            get_node_relationships_between(label, label, self.user, self.AI)
        )
        nodes = [node for node in [AI[0], user[0]] if node is not None]
        relationships = relationships if relationships is not None else []
        self.character_settings = Triplets(nodes=nodes, relationships=relationships)

        # user, AIのname_variationを含めたname_listを取得する。
        character_name_list = []
        for node in self.character_settings.nodes:
            character_name_list.append(node.name)
            if node.properties.get("name_variation"):
                character_name_list += node.properties.get("name_variation")
        self.character_name_lsit = character_name_list

        # load short_memory
        short_memory = []
        messages = get_messages(self.title, n=self.short_memory_limit)
        if messages:
            node_ids = [message.id for message in messages]
            latest_message_id = node_ids[0]
        short_memory = get_message_entities(node_ids)

        self.latest_message_id = latest_message_id
        self.short_memory = ShortMemory(short_memory=short_memory, limit=self.short_memory_limit)
        self.short_memory.convert_to_tripltets()

    def set_user_input(self, user_input: str):
        self.user_input = user_input

# Chat
    def create_chat_prompt(self):
        # system_prompt
        system_prompt = """Output line in Japanese without character name.
                        Don't reveal hidden information.
                        """
        character_settings_prompt = self.character_settings.model_dump_json()

        character_prompt = f"""
        You are to simulate the game character that the young girl named {self.AI}, that have conversation with the player named {self.user}.
        Output the line of {self.AI} without character name.
        If the relationship has "Scenario Flag" type, you must start the scenario by following the instructions in the properties.
        ----------------------------------------
        Current Time: {self.current_time}
        Location: {self.location}
        ----------------------------------------
        Character Settings:
        {character_settings_prompt}
        """

        system_prompt += character_prompt

        # short_memory, retrieved_memoryの重複を排除して、memory_infoに追加する。
        if self.retrieved_memory and self.short_memory.triplets:
            self.retrieved_memory.nodes = list(set(self.retrieved_memory.nodes + self.short_memory.triplets.nodes))
            self.retrieved_memory.relationships = list(set(self.retrieved_memory.relationships + self.short_memory.triplets.relationships))

        memory_info = ""
        if self.short_memory.triplets:
            memory_info += self.short_memory.triplets.to_cypher_json()
        if self.retrieved_memory:
            memory_info += self.retrieved_memory.to_cypher_json()
        # memory_infoをself.short_memory_input_sizeを上限にする。
        if len(memory_info) > self.short_memory_input_size:
            memory_info = memory_info[-self.short_memory_input_size:]

        # memory_infoが存在すればそれを、存在しなければ'Searching'をsystem_promptに追加
        system_prompt += f"""
        ----------------------------------------
        Background information from your memory (Message is the past conversation lines.):
        {memory_info if memory_info else "'Searching. wait a moment.'"}
        ----------------------------------------
        """

        # user_prompt
        user_prompt = f"""user: {self.user_input}"""

        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
            short_memory=self.short_memory.short_memory,    # short_memoryから、会話履歴を追加
        ).create_messages()
        return messages

    async def streamchat(self, max_tokens: int, websocket: WebSocket | None = None):
        # prompt生成
        messages = self.create_chat_prompt()
        logger.info(f"messages: {messages}")

        # response生成
        response = await self.client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            frequency_penalty=0.3,  # 繰り返しを抑制するために必須。
            stream=True,
        )

        full_text = ""
        accumulated_text = ""
        inside_code_block = False
        audio_chunk = ""
        # [TODO] 名前が出力される場合のハンドリング
        async for chunk in response:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                full_text += content
                accumulated_text += content

            while True:
                # コードブロックの処理
                if inside_code_block:
                    # コードブロックの終了記号を検出した場合
                    code_block_end = accumulated_text.find("```")
                    if code_block_end != -1:
                        inside_code_block = False
                        code_block = accumulated_text[:code_block_end+3]        # Include the end marker
                        await handle_code_block(code_block, websocket)
                        accumulated_text = accumulated_text[code_block_end+3:]  # Remove processed part
                    # コードブロックを継続
                    else:
                        break
                # 通常の音声合成処理
                else:
                    match = re.search(r'([\n。！？；]+|\n\n|```)', accumulated_text)
                    if match:
                        # コードブロックの開始記号を検出した場合
                        if match.group() == '```':
                            inside_code_block = True

                        # 終端記号を検出した場合
                        else:
                            sentence_end = match.end()
                            sentence = accumulated_text[:sentence_end]
                            await wb_get_voice(sentence, websocket)
                            accumulated_text = accumulated_text[sentence_end:]
                    else:
                        break

        # 残りのテキストを音声合成する。
        if accumulated_text:
            await wb_get_voice(audio_chunk, websocket)

        logger.info(full_text)
        return full_text

    def close_chat(self, message: MessageNode):
        # user,AIの要素がある場合、Character_settingsに反映する。
        # self.chatacter_settings(user,AIの要素)のうち、self.retrieved_memory.nodesと一致するものを更新する。
        self.character_settings.nodes = [
            next((rm_node for rm_node in self.retrieved_memory.nodes if rm_node.name == node.name and rm_node.label == node.label), node)
            for node in self.character_settings.nodes
        ]
        # self.retrieved_memoryからは、self.character_settings(user,AIの要素)を除外する。
        self.retrieved_memory.nodes = [
            rm_node for rm_node in self.retrieved_memory.nodes
            if not any(node.name == rm_node.name and node.label == rm_node.label for node in self.character_settings.nodes)
        ]

        # message, retrieved_memoryをまとめて、short_memory classに格納する。
        self.short_memory.memory_turn_over(
            message=message,
            retrieved_memory=self.retrieved_memory
        )

        # user_input_entity、retrieved_memoryをリセット
        self.user_input_entity = None
        self.retrieved_memory = None
        logger.debug(f"client title: {self.title}")
        logger.debug(f"short_memory: {self.short_memory.short_memory}")

    def _contain_terminal_symbol(self, text):
        """終端記号を含むかどうかを確認する"""
        pattern = r"[\n。！？；]+|\n\n"
        return re.search(pattern, text) is not None

    def _split_at_terminal_symbol(self, text):
        """テキストを終端記号で分割する"""
        pattern = r"([\n。！？；]+|\n\n)"
        parts = re.split(pattern, text)
        sentences = []
        for i in range(0, len(parts) - 1, 2):
            sentence = parts[i] + parts[i + 1]
            sentence = sentence.strip()
            if sentence:
                sentences.append(sentence)
        return sentences

# Get memory
    async def wb_get_memory(self, websocket: WebSocket | None = None):
        """①user_inputに関連するmessageをベクトル検索し、関連するnode, relationshipを取得する。
        ②user_inputのentityを取得し、関連するnode, relationshipを取得する。"""

        message_retrieved_memory, entity_retrieved_memory = await asyncio.gather(
            self._retrieve_message_entity(self.user_input),
            self._retrieve_entity(self.user_input)
        )
        logger.info(f"message_retrieved_memory: {len(message_retrieved_memory.nodes)} nodes, {len(message_retrieved_memory.relationships)} relationships" if message_retrieved_memory else "message_retrieved_memory: None")
        logger.info(f"entity_retrieved_memory: {len(entity_retrieved_memory.nodes)} nodes, {len(entity_retrieved_memory.relationships)} relationships" if entity_retrieved_memory else "entity_retrieved_memory: None")

        # ①②の結果を統合し、retrieved_memory(short_memoryにつながる)に格納する。
        nodes = set()
        relationships = set()
        if message_retrieved_memory:
            nodes = set(message_retrieved_memory.nodes)
            relationships = set(message_retrieved_memory.relationships)
        if entity_retrieved_memory:
            nodes = set(entity_retrieved_memory.nodes)
            relationships = set(entity_retrieved_memory.relationships)
        self.retrieved_memory = Triplets(nodes=list(nodes), relationships=list(relationships))
        logger.info(f"retrieved_memory: {len(self.retrieved_memory.nodes)} nodes, {len(self.retrieved_memory.relationships)} relationships")

        # tripletsとMessage_nodeを別々のデータとしてwebsocketに送信
        if self.retrieved_memory:
            # websocket接続している場合、retrieved_memoryを送信する。
            if websocket:
                message = {"type": "retrieved_memory",
                           "retrieved_memory":  self.retrieved_memory.model_dump_json()}   # related entity
                await websocket.send_text(json.dumps(message))

    async def _retrieve_message_entity(self, text: str, **kwargs):
        """ベクトル検索したmessageから、深さn-1までのentityを抽出する。合計1秒程度。"""
        depth = self.short_memory_depth - 1 if self.short_memory_depth > 1 else 1

        # ベクトル検索したmessageを最大k個取得する
        messages = await query_messages(query=text, **kwargs)

        # Messageのuser_input_nameから、entity名を抽出する。
        entities = set()
        if messages:
            for message in messages:
                user_input_entity = message.user_input_entity
                node_names = [node.name for node in user_input_entity.nodes] if user_input_entity else None
                if node_names:
                    entities = entities.union(node_names)
        entities = [entity for entity in entities if entity not in self.character_name_lsit]        # entitiesから、user, aiのnameを除外する。
        logger.info(f"entities: {entities}")

        # entityから、深さn-1までのnode, relationshipを取得する。
        return await get_node_relationships(names=entities, depth=depth)

    async def _retrieve_entity(self, text: str):
        """user_inputから、深さnまでのentityを抽出する。合計3秒程度。"""
        depth = self.short_memory_depth if self.short_memory_depth > 1 else 1

        # user_inputから、entityを抽出する。
        user_input_entity = await TripletsConverter(short_memory=self.short_memory.short_memory).extract_entites(text)
        if user_input_entity:
            entities = [remove_suffix(entity) for entity in user_input_entity]                      # entityの末尾に付与されるsuffixを削除する。
            entities = [entity for entity in entities if entity not in self.character_name_lsit]    # entitiesから、user, aiのnameを除外する。
            logger.info(f"entities: {entities}")

            # entityから、深さnまでのnode, relationshipを取得する。
            return await get_node_relationships(names=entities, depth=depth)

# Store memory
    async def wb_store_memory(self):
        """user_input_entityを抽出し、Neo4jに保存する。"""
    # user_input_entity
        converter = TripletsConverter(client=self.client,
                                      user_name=self.user,
                                      ai_name=self.AI,
                                      time_zone=self.time_zone,
                                      short_memory=self.short_memory.short_memory)
        # triage text
        self.user_input_type = await converter.triage_text(self.user_input)
        # convert text to triplets
        triplets = await converter.run_sequences(self.user_input)
        if triplets is None:
            return None
        # websocket終了時に実行するstore_messageに渡すため、selfに格納。
        self.user_input_entity = triplets
        logger.info(f"user_input_entity: {triplets.to_cypher_json()}")

    # Store Triplets in Neo4j
        if converter.user_input_type != "question" and triplets:
            await converter.store_memory_from_triplet(triplets)

# Generate response
    async def wb_generate_audio(self, websocket: WebSocket):
        """テキスト生成から音声合成、再生までを統括する関数"""
        # レスポンス作成前に、user_inputを音声合成して送信
        await wb_get_voice(self.user_input, websocket, narrator="Asumi Shuo")

        # neo4jからのレスポンスを待つ
        if self.retrieved_memory is None:
            for _ in range(10):  # 通常、1秒以内に取得される。
                if self.retrieved_memory is not None:
                    break
                await asyncio.sleep(0.3)

        # response生成
        max_tokens = 140
        self.ai_response = await self.streamchat(max_tokens, websocket)

    # テキスト生成だけを行う関数
    async def wb_generate_text(self, websocket: WebSocket):
        if self.retrieved_memory is None:
            for _ in range(10):
                if self.retrieved_memory is not None:
                    break
                await asyncio.sleep(0.3)
                max_tokens = 140

        # response生成
        # prompt生成
        messages = self.create_chat_prompt()
        logger.info(f"messages: {messages}")

        # response生成
        response = await self.client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            frequency_penalty=0.3,  # 繰り返しを抑制するために必須。
            stream=True,
        )
        fulltext = ""
        async for chunk in response:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                fulltext += content

                # [HACK] チャンクごとに返す場合のコード
                # accumulated_text += content
                # if re.search(r'([\n。！？；]+|\n\n|```)', accumulated_text):
                message = {
                    "type": "text",
                    "text": content,
                }
                await websocket.send_text(json.dumps(message))  # JSONとして送信
        logger.info(fulltext)
        self.ai_response = fulltext
        return fulltext

    # テキスト生成だけを行う関数(非websocket)
    async def generate_text(self):
        if self.retrieved_memory is None:
            for _ in range(10):
                if self.retrieved_memory is not None:
                    break
                await asyncio.sleep(0.3)
                max_tokens = 140

        # response生成
        # prompt生成
        messages = self.create_chat_prompt()
        logger.info(f"messages: {messages}")

        # response生成
        response = await self.client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            frequency_penalty=0.3,  # 繰り返しを抑制するために必須。
            stream=True,
        )

        fulltext = ""
        async for chunk in response:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                sys.stdout.write(content)
                sys.stdout.flush()
                fulltext += content

        self.ai_response = fulltext
        return fulltext


# コードブロックテキストをWebSoketで送り返す。
async def handle_code_block(code_block_content: str, websocket: WebSocket):
    # ```の行を削除してから、フロントエンドに送る。
    # code = "\n".join(code_block_content)
    code = "\n".join(line for line in code_block_content if "```" not in line.strip())
    print(f"code: {code}")
    message = {"type": "code", "code": code}
    await websocket.send_text(json.dumps(message))


# 音声合成
async def wb_get_voice(text: str, websocket: WebSocket, narrator: str = "Asumi Ririse"):
    logger.info(f"get_voice: {text}")
    text = text.replace(".", "、")  # 1. 2. のような箇条書きを、ポーズとして認識可能な1、2、に変換する。
    audio_path = await get_voice(text, narrator=narrator)

    # 最大10秒間、ファイルが存在するか確認
    for _ in range(10):
        if os.path.exists(audio_path):
            break
        sleep(1.0)

    if os.path.exists(audio_path):
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        # バイナリデータをBase64エンコードしてJSONに格納
        encoded_audio = base64.b64encode(audio_data).decode("utf-8")
        message = {
            "type": "audio",
            "audioData": encoded_audio,
            "text": text if narrator == "Asumi Ririse" else "",
        }  # ここに送りたいテキストをセット

        await websocket.send_text(json.dumps(message))  # JSONとして送信
        os.remove(audio_path)   # 音声ファイルを削除
    else:
        logger.error("Failed to get voice after multiple attempts.")
