import os
import json
import re
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
from chat_wb.neo4j.memory import query_messages
from chat_wb.models import Triplets, WebSocketInputData, ShortMemory

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
        # 初期化時に、character_settingsの読み込みを行う。
        await stream_chat_clients[title].init()
    else:
        stream_chat_clients[title].set_user_input(input_data.input_text)
    return stream_chat_clients[title]


# AIの会話応答を行うするクラス
class StreamChatClient():
    def __init__(self, input_data: WebSocketInputData) -> None:
        self.user = input_data.user
        self.AI = input_data.AI
        self.title = input_data.title
        self.client = AsyncOpenAI()
        self.user_input: str = input_data.input_text
        self.user_input_type: str | None = None  # user_inputのタイプ（question, statement, command, etc.）
        self.user_input_entity: Triplets | None = None  # ユーザー入力から抽出したTriplets
        self.temp_memory: list[str] = []   # ai_responseの一時保存
        self.message_retrieved_memory: Triplets | None = None    # Messageに基づいて、neo4jから取得した一時的な情報
        self.retrieved_memory: Triplets | None = None  # neo4jから取得した情報の一時保存
        self.short_memory: ShortMemory = ShortMemory()  # チャットとlong_memoryの履歴、memoryを最大7個まで格納する

    async def init(self):
        label = "Person"
        AI, user, relationships = await asyncio.gather(
            get_node(label, self.AI),
            get_node(label, self.user),
            get_node_relationships_between(label, label, self.user, self.AI)
        )
        nodes = [node for node in [AI[0], user[0]] if node is not None]
        relationships = relationships if relationships is not None else []
        self.character_settings = Triplets(nodes=nodes, relationships=relationships).model_dump_json()

    def set_user_input(self, user_input: str):
        self.user_input = user_input

    # 短い文章で出力を返す（これ複数回で1回の返答）
    async def streamchat(self, k: int, input_text: str | None = None, message_retrieved_memory: Triplets | None = None, max_tokens: int = 240):
        # system_prompt
        system_prompt = """Output line in Japanese without character name.
                        Don't reveal hidden information.
                        """
        # user, AIのノード、両者間のリレーションシップを取得してsystem_promptに設定する。（setからの除去等、short_memoryとの重複を検討する。（この情報を更新するタイミングがないので、重複しても良いかもしれない。)）
        character_settings_prompt = self.character_settings

        character_prompt = f"""
        You are to simulate the game character that the young girl named {self.AI}, that have conversation with the player named {self.user}.
        Output the line of {self.AI}.
        If the relationship has "Scenario Flag" type, you must start the scenario by following the instructions in the properties.
        ----------------------------------------
        Character Settings:
        {character_settings_prompt}
        """

        system_prompt += character_prompt

        memory_info = ""
        if self.short_memory.triplets:
            memory_info += self.short_memory.triplets.model_dump_json()
        if self.message_retrieved_memory:
            memory_info += self.message_retrieved_memory.model_dump_json()

        # memory_infoが存在すればそれを、存在しなければ'Searching'をsystem_promptに追加
        system_prompt += f"""
        ----------------------------------------
        Background information from your memory (Message is the past conversation lines.):
        {memory_info if memory_info else "'Searching. wait a moment.'"}
        ----------------------------------------
        """
        logger.info(f"system_prompt: {system_prompt}")

        # user_prompt
        # 1回目のuser_prompt
        if input_text is not None:
            user_prompt = f"""user: {input_text}"""
        # 2回目以降のuser_prompt（ちょっと無茶しているプロンプト）
        else:
            user_prompt = f"""user: {self.user_input}
                              user:continue it."""

        # ai_prompt
        ai_prompt = "".join(self.temp_memory)   # 単純にこれまでの履歴を入れた場合、それに続けて生成される。

        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
            assistant_message=ai_prompt,
            short_memory=self.short_memory.short_memory,    # short_memoryから、会話履歴を追加
        ).create_messages()

        # response生成
        response = await self.client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
            max_tokens=max_tokens,  # 240をベースにする。初回のみ応答速度を上げるために、120で渡す。
            temperature=0.7,
            frequency_penalty=0.3,  # 繰り返しを抑制するために必須。
        )
        response_text = response.choices[0].message.content
        return response_text

    def close_chat(self):
        # user_input, ai_response, retrieved_memoryをまとめて、short_memory classに格納する。
        self.short_memory.memory_turn_over(
            user_input=self.user_input,
            ai_response="\n".join(self.temp_memory),
            retrieved_memory=self.retrieved_memory
        )

        # user_input_entity、temp_memory、retrieved_memoryをリセット
        self.user_input_entity = None
        self.temp_memory = []
        self.retrieved_memory = None
        logger.debug(f"client title: {self.title}")
        logger.debug(f"short_memory: {self.short_memory.short_memory}")

    # テキストを終端記号で分割する関数
    def format_text(self, text):
        if not text:
            return []

        # 文章を分割するときに記号を保持するための正規表現
        pattern = r"([\n。！？；]+|\n\n)"

        # split with capturing group will return the delimiters as well.
        parts = re.split(pattern, text)
        sentences = []
        for i in range(0, len(parts) - 1, 2):
            # concatenate the sentence and its ending delimiter
            sentence = parts[i] + parts[i + 1]
            sentence = sentence.strip()
            if sentence:
                sentences.append(sentence)

        # 末尾の文が終端記号で終わっているか確認
        if not re.search(pattern, parts[-1]):
            self.partial_text = parts[-1]
            # sentencesの最後の要素が終端記号で終わらない場合、それを削除
            if sentences:
                if not re.search(pattern, sentences[-1]):
                    sentences.pop()

        return sentences

    async def wb_get_memory(self, websocket: WebSocket):
        """user_inputに関連するmessageをベクトル検索し、関連するnode, relationshipを取得する。
        messages: Message Node, activated_memory: Related Entity"""
        # 過去のMessageと、entityを取得する。
        message_nodes, entity = query_messages(self.user_input)
        # entityに関連するnode, relationshipを取り出す。
        converter = TripletsConverter(client=self.client, user_name=self.user, ai_name=self.AI)
        message_retrieved_memory = await converter.get_memory_from_triplet(entity)
        if message_retrieved_memory is None:
            return None
        # Message, tripletsをwebsocketに送信
        if self.message_retrieved_memory:
            messages = Triplets(nodes=message_nodes)    # josn変換のため、Tripletsに格納
            message = {"type": "messages",
                       "messages": messages.model_dump_json(),  # message nodes
                       "message_retrieved_memory":  message_retrieved_memory.model_dump_json()}   # related entity
            await websocket.send_text(json.dumps(message))

        # result.nodesにmessage_nodeを追加
        message_retrieved_memory.nodes.extend(message_nodes)
        logger.info(f"message_retrieved_memory: {len(message_retrieved_memory.nodes)} nodes, {len(message_retrieved_memory.relationships)} relationships")
        self.message_retrieved_memory = message_retrieved_memory

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
        result = await converter.get_memory_from_triplet(triplets)
        if result is None:
            return None
        logger.info(f"retrieved_memory: {len(result.nodes)} nodes, {len(result.relationships)} relationships")
        self.retrieved_memory = result

    # Store Triplets in Neo4j
        if converter.user_input_type != "question" and triplets:
            await converter.store_memory_from_triplet(triplets)

    # テキスト生成から音声合成、再生までを統括する関数
    async def wb_generate_audio(
        self, websocket: WebSocket, k: int = 2
    ):
        # レスポンス作成前に、user_inputを音声合成して送信
        await _get_voice(self.user_input, websocket, narrator="Asumi Shuo")

        if self.message_retrieved_memory is None:
            for _ in range(10):  # 通常、1秒以内に取得される。
                if self.message_retrieved_memory is not None:
                    break
                await asyncio.sleep(0.3)

        # historyと同じ内容かどうかを調べて、同じなら生成しないようにできるかもしれない。（function callingか）
        code_block = []
        inside_code_block = False

        for i in range(k):
            logger.info(f"i: {i}")
            max_tokens = 80 if i == 0 else 240  # 初回応答速度を上げるために、80で渡す。
            input_text = self.user_input if i == 0 else None  # 初回のみ受け取ったテキストを渡す。
            response = await self.streamchat(
                k=k, input_text=input_text, max_tokens=max_tokens, message_retrieved_memory=self.message_retrieved_memory
            )  # ここにself.message_retrieved_memoryを入れておけば、変更されたタイミングで、適用される。

            # テキストを正規表現で分割してリストに整形
            formatted_text = self.format_text(response)

            # 既にテキストが存在するかどうかを確認し、繰り返しレスポンスになっている場合、そこで中断する。
            for text in formatted_text:
                if text in self.temp_memory:
                    return "\n".join(self.temp_memory)

            # 整形した文章（終端記号区切り）をtemp_memoryに追加
            self.temp_memory.extend(formatted_text)

            texts_for_get_audio = ""
            # """を含むコードブロックの確認
            for text in formatted_text:
                if "```" in text:
                    if not inside_code_block:  # Starting a new code block
                        inside_code_block = True
                        code_block.append(text)
                    else:  # Ending an existing code block
                        inside_code_block = False
                        code_block.append(text)
                        await handle_code_block(code_block, websocket)
                        code_block = []
                    continue

                if (
                    inside_code_block
                ):  # If inside a code block, just append the text to code_block
                    code_block.append(text)
                    continue

                # コードブロックでない場合、音声合成を行う。
                else:
                    texts_for_get_audio += text

            # 雑談のような短文の場合、Voicepeakの1processが遅いため、集約して渡す。（音声合成ソフトウェアの改善待ち）
            await _get_voice(texts_for_get_audio, websocket)

        logger.info(f"temp_memory: {self.temp_memory}")


# コードブロックテキストをWebSoketで送り返す。
async def handle_code_block(code_block_content, websocket: WebSocket):
    # ```の行を削除してから、フロントエンドに送る。
    # code = "\n".join(code_block_content)
    code = "\n".join(line for line in code_block_content if "```" not in line.strip())
    print(f"code: {code}")
    message = {"type": "code", "code": code}
    await websocket.send_text(json.dumps(message))


# 音声合成
async def _get_voice(text: str, websocket: WebSocket, narrator: str = "Asumi Ririse"):
    text = text.replace(".", "、")  # 1. 2. のような箇条書きを、ポーズとして認識可能な1、2、に変換する。
    audio_path = await get_voice(text, narrator=narrator)

    # 最大5秒間、ファイルが存在するか確認
    for _ in range(50):  # 0.1秒 * 20回 = 2秒
        if os.path.exists(audio_path):
            break
        sleep(0.1)

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
