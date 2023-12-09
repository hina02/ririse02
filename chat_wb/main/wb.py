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
from chat_wb.models.neo4j import Triplets
from chat_wb.models.wb import WebSocketInputData
from chat_wb.models.wb import ShortMemory

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


def get_stream_chat_client(input_data: WebSocketInputData):
    title = input_data.title
    if title not in stream_chat_clients:
        stream_chat_clients[title] = StreamChatClient(input_data)
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
        self.user_input_entity: Triplets | None = None  # ユーザー入力から抽出したTriplets
        self.temp_memory: list[str] = []   # ai_responseの一時保存
        self.long_memory: Triplets | None = None  # neo4jから取得した情報の一時保存
        self.short_memory: ShortMemory = ShortMemory()  # チャットとlong_memoryの履歴、memoryを最大7個まで格納する
        self.activated_memory: Triplets | None = None   # short_memoryのうち、user_input_entityに関連するもの

    def set_user_input(self, user_input: str):
        self.user_input = user_input

    # 短い文章で出力を返す（これ複数回で1回の返答）
    async def streamchat(self, k: int, input_text: str | None = None, long_memory: Triplets | None = None, max_tokens: int = 240):
        # system_prompt
        system_prompt = """Output is Japanese.
                        This is a friendly chat.
                        If you can't answer, please ask 'wait', while you are 'searching' your memory.
                        Don't reveal hidden information.
                        """

        # activated_memoryとlong_memoryの追加
        memory_info = None
        if self.activated_memory:
            memory_info = self.activated_memory.model_dump_json()
        elif long_memory:
            self.long_memory = long_memory
            memory_info = long_memory.model_dump_json()

        # memory_infoが存在すればそれを、存在しなければ'Searching'をsystem_promptに追加
        system_prompt += f"""
        ----------------------------------------
        Background information from your memory:
        {memory_info if memory_info else "'Searching. wait a moment.'"}
        ----------------------------------------
        """
        # logger.info(f"system_prompt: {system_prompt}")

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
            max_tokens=max_tokens,  # 240をベースにする。初回のみ応答速度を上げるために、80で渡す。
            temperature=0.7,
            frequency_penalty=0.3,  # 繰り返しを抑制するために必須。
        )
        response_text = response.choices[0].message.content
        return response_text

    def close_chat(self):
        # user_input, ai_response, long_memoryをまとめて、short_memory classに格納する。
        self.short_memory.memory_turn_over(
            user_input=self.user_input,
            ai_response="\n".join(self.temp_memory),
            long_memory=self.long_memory
        )

        # user_input_entity、temp_memory、long_memory、activated_memoryをリセット
        self.user_input_entity = None
        self.temp_memory = []
        self.long_memory = None
        self.activated_memory = None
        logger.info(f"client title: {self.title}")
        logger.info(f"short_memory: {self.short_memory}")

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

    # websocketに対応して、tripletの抽出、保存を行い、検索結果を送信する関数
    async def wb_get_memory_from_triplet(self, websocket: WebSocket):
        # textからTriplets(list[Node], list[Relationship])を抽出
        converter = TripletsConverter(client=self.client, user_name=self.user, ai_name=self.AI)
        triplets = await converter.run_sequences(self.user_input)
        logger.info(f"triplets: {triplets}")
        if triplets is None:
            return None  # 出力なしの場合は、Noneを返す。

        # store_messageに渡すため、selfに格納。
        self.user_input_entity = triplets

        # short_memoryからの関連情報の選択
        self.activated_memory = self.short_memory.activate_memory(self.user_input_entity)

        # websocketにactivated_memoryを送信
        message = {"type": "entity", "entity": self.activated_memory.model_dump_json() if self.activated_memory else None}
        await websocket.send_text(json.dumps(message))

        # short_memoryからの関連情報の選択
        self.activated_memory = self.short_memory.activate_memory(self.user_input_entity)

        # websocketにactivated_memoryを送信
        message = {"type": "entity", "entity": self.activated_memory.dict()}
        await websocket.send_text(json.dumps(message))

        # Neo4jから、Tripletsに含まれるノードと関係を取得
        result = await converter.get_memory_from_triplet(triplets)
        if result is None:
            return None
        logger.info(f"long_memory: {result}")
        self.long_memory = result

        # user_inputが質問文でない場合、TripletsをNeo4jに保存
        if converter.text_type != "question" and triplets:
            await converter.store_memory_from_triplet(triplets)

    # テキスト生成から音声合成、再生までを統括する関数
    async def wb_generate_audio(
        self, websocket: WebSocket, k: int = 4
    ):
        # レスポンス作成前に、user_inputを音声合成して送信
        await _get_voice(self.user_input, websocket, narrator="Asumi Shuo")

        # historyと同じ内容かどうかを調べて、同じなら生成しないようにできるかもしれない。（function callingか）
        code_block = []
        inside_code_block = False

        for i in range(k):
            max_tokens = 80 if i == 0 else 160 if i == 1 else 240  # 初回応答速度を上げるために、80で渡す。段階的に増加。
            input_text = self.user_input if i == 0 else None  # 初回のみ受け取ったテキストを渡す。
            response = await self.streamchat(
                k=k, input_text=input_text, max_tokens=max_tokens, long_memory=self.long_memory
            )  # ここにentityを入れれば、global変数が変更されたタイミングで、適用される。

            # テキストを正規表現で分割してリストに整形
            formatted_text = self.format_text(response)

            # 既にテキストが存在するかどうかを確認し、繰り返しレスポンスになっている場合、そこで中断する。
            for text in formatted_text:
                if text in self.temp_memory:
                    return "\n".join(self.temp_memory)

            # 整形した文章（終端記号区切り）をtemp_memoryに追加
            self.temp_memory.extend(formatted_text)

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
                    await _get_voice(text, websocket)

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
