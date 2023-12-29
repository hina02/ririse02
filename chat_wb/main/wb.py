import os
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
from chat_wb.neo4j.neo4j import get_node, get_node_relationships_between
from chat_wb.neo4j.memory import query_messages, get_latest_messages
from chat_wb.models import Triplets, WebSocketInputData, ShortMemory, TempMemory

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
        stream_chat_clients[title].set_user_input(input_data.input_text)
    return stream_chat_clients[title]


# AIの会話応答を行うするクラス
class StreamChatClient():
    def __init__(self, input_data: WebSocketInputData) -> None:
        self.time_zone = "Asia/Tokyo"   # [TODO] User Setting
        self.current_time = datetime.now(pytz.timezone(self.time_zone)).strftime("%Y-%m-%d %H:%M:%S")
        self.location = "Yokohama"      # [TODO] User node properties and AI node properties
        self.user = input_data.user
        self.AI = input_data.AI
        self.title = input_data.title
        self.latest_message_id: int | None = None
        self.client = AsyncOpenAI()
        self.user_input: str = input_data.input_text
        self.user_input_type: str | None = None  # 不要なTripletsを保存しないための分類（code, documents, chat, question）
        self.user_input_entity: Triplets | None = None  # ユーザー入力から抽出したTriplets
        self.ai_response: str | None = None   # ai_responseの一時保存
        self.message_retrieved_memory: Triplets | None = None    # Messageに基づいて、neo4jから取得した一時的な情報
        self.retrieved_memory: Triplets | None = None  # neo4jから取得した情報の一時保存
        self.short_memory: ShortMemory  # チャットとlong_memoryの履歴、memoryを最大7個まで格納する
        self.short_memory_limit = 7     # [TODO] User Setting
        self.short_memory_depth = 1     # [TODO] User Setting
        self.short_memory_input_size = 4096  # [TODO] User Setting

    async def init(self):
        # load character_settings
        label = "Person"
        AI, user, relationships = await asyncio.gather(
            get_node(label, self.AI),
            get_node(label, self.user),
            get_node_relationships_between(label, label, self.user, self.AI)
        )
        nodes = [node for node in [AI[0], user[0]] if node is not None]
        relationships = relationships if relationships is not None else []
        self.character_settings = Triplets(nodes=nodes, relationships=relationships).model_dump_json()

        # load short_memory
        short_memory = []
        messages = get_latest_messages(self.title, n=self.short_memory_limit)
        if messages:
            for message in reversed(messages):
                short_memory.append(
                    TempMemory(
                        user_input=message["user_input"],
                        ai_response=message["ai_response"],
                        triplets=json.loads(message["user_input_entity"]) if message["user_input_entity"] else None,
                        time=message["create_time"].to_native()
                    )
                )
        self.latest_message_id = messages[0].id if messages else None
        self.short_memory = ShortMemory(short_memory=short_memory, limit=self.short_memory_limit)
        self.short_memory.convert_to_tripltets()

    def set_user_input(self, user_input: str):
        self.user_input = user_input

    def create_chat_prompt(self):
        # system_prompt
        system_prompt = """Output line in Japanese without character name.
                        Don't reveal hidden information.
                        """
        # user, AIのノード、両者間のリレーションシップを取得してsystem_promptに設定する。
        character_settings_prompt = self.character_settings

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
        if self.message_retrieved_memory and self.short_memory.triplets:

            combined_nodes = self.message_retrieved_memory.nodes + self.short_memory.triplets.nodes
            combined_relationships = self.message_retrieved_memory.relationships + self.short_memory.triplets.relationships
            unique_nodes = list(set(combined_nodes))
            unique_relationships = list(set(combined_relationships))
            self.message_retrieved_memory.nodes = unique_nodes
            self.message_retrieved_memory.relationships = unique_relationships

        memory_info = ""
        if self.short_memory.triplets:
            memory_info += self.short_memory.triplets.to_cypher_json()
        if self.message_retrieved_memory:
            memory_info += self.message_retrieved_memory.to_cypher_json()
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

    def close_chat(self):
        # user_input, ai_response, retrieved_memoryをまとめて、short_memory classに格納する。
        self.short_memory.memory_turn_over(
            user_input=self.user_input,
            ai_response=self.ai_response,
            retrieved_memory=self.retrieved_memory
        )

        # user_input_entity、temp_memory、retrieved_memory、message_retrieved_memoryをリセット
        self.user_input_entity = None
        self.temp_memory = None
        self.retrieved_memory = None
        self.message_retrieved_memory = None
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

    async def wb_get_memory(self, websocket: WebSocket | None = None):
        """user_inputに関連するmessageをベクトル検索し、関連するnode, relationshipを取得する。
        messages: Message Node, activated_memory: Related Entity"""
        start_time = datetime.now()
        logger.info(f"start_wb_get_memory: {start_time}")
        # 過去のMessageと、entityを取得する。
        message_nodes, entity = await query_messages(self.user_input)
        interval_time = datetime.now()
        logger.info(f"query_messages: {interval_time - start_time}")
        # entityに関連するnode, relationshipを取り出す。
        message_retrieved_memory = await TripletsConverter.get_memory_from_triplet(
            triplets=entity,
            AI=self.AI,
            user=self.user,
            depth=self.short_memory_depth)
        end_time = datetime.now()
        logger.info(f"get_memory_from_triplet: {end_time - start_time}")

        logger.info(f"message_retrieved_memory: {len(message_retrieved_memory.nodes)} nodes, {len(message_retrieved_memory.relationships)} relationships")
        self.message_retrieved_memory = message_retrieved_memory

        # tripletsとMessage_nodeを別々のデータとしてwebsocketに送信
        if message_retrieved_memory:
            # websocket接続している場合、message_retrieved_memoryを送信する。
            if websocket:
                messages = Triplets(nodes=message_nodes)    # josn変換のため、Tripletsに格納
                message = {"type": "messages",
                           "messages": messages.model_dump_json(),  # message nodes
                           "message_retrieved_memory":  message_retrieved_memory.model_dump_json()}   # related entity
                await websocket.send_text(json.dumps(message))

    async def wb_store_memory(self):
        """user_input_entityを抽出し、Neo4jに保存する。また、retrieve memoryする。"""
    # user_input_entity
        converter = TripletsConverter(client=self.client, user_name=self.user, ai_name=self.AI)
        # triage text
        self.user_input_type = await converter.triage_text(self.user_input)
        # convert text to triplets
        triplets = await converter.run_sequences(self.user_input, self.short_memory.short_memory)
        if triplets is None:
            return None
        # websocket終了時に実行するstore_messageに渡すため、selfに格納。
        self.user_input_entity = triplets

    # retrieve memory
        # Neo4jから、user_input_entityに関連したnode,relationshipsを取得し、short_memoryに格納
        result = await converter.get_memory_from_triplet(
            triplets=triplets,
            AI=self.AI,
            user=self.user,
            depth=self.short_memory_depth)
        if result is None:
            return None
        logger.info(f"retrieved_memory: {len(result.nodes)} nodes, {len(result.relationships)} relationships")
        self.retrieved_memory = result

    # Store Triplets in Neo4j
        if converter.user_input_type != "question" and triplets:
            await converter.store_memory_from_triplet(triplets)

    # テキスト生成から音声合成、再生までを統括する関数
    async def wb_generate_audio(self, websocket: WebSocket):
        # レスポンス作成前に、user_inputを音声合成して送信
        await wb_get_voice(self.user_input, websocket, narrator="Asumi Shuo")

        # neo4jからのレスポンスを待つ
        if self.message_retrieved_memory is None:
            for _ in range(10):  # 通常、1秒以内に取得される。
                if self.message_retrieved_memory is not None:
                    break
                await asyncio.sleep(0.3)

        # response生成
        max_tokens = 140
        self.ai_response = await self.streamchat(max_tokens, websocket)

    # テキスト生成だけを行う関数
    async def generate_text(self):
        if self.message_retrieved_memory is None:
            for _ in range(10):  # 通常、1秒以内に取得される。
                if self.message_retrieved_memory is not None:
                    break
                await asyncio.sleep(0.3)

        max_tokens = 256
        # 生成したテキストを取得（responseを早くするため、max_tokensを小さくして繰り返す）
        response = await self.streamchat(max_tokens)

        return response

    # テキスト生成だけを行う関数
    async def wb_generate_text(self, websocket: WebSocket):
        if self.message_retrieved_memory is None:
            for _ in range(10):
                if self.message_retrieved_memory is not None:
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
