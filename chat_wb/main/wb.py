import os
import json
import re
from logging import getLogger
import base64
import asyncio
from fastapi import WebSocket
from openai import OpenAI
from openai_api.models import ChatPrompt
from chat_wb.voice.text2voice import playVoicePeak
from chat_wb.neo4j.triplet import get_graph_from_triplet
from chat_wb.models.wb import WebSocketInputData

logger = getLogger(__name__)


# 音声合成して、wavファイルのfilepathを返す
async def get_voice(text: str):
    file_path = await playVoicePeak(script=text, narrator="Asumi Ririse")

    if not file_path:
        return {
            "status": "queued",
            "message": "Your request is queued. Please check back later.",
        }
    return file_path


logger = getLogger(__name__)


# StreamChatClientを管理する辞書
stream_chat_clients = {}


def get_stream_chat_client(title: str):
    if title not in stream_chat_clients:
        stream_chat_clients[title] = StreamChatClient()
    return stream_chat_clients[title]


# AIの会話応答を行うするクラス
class StreamChatClient:
    def __init__(self) -> None:
        self.client = OpenAI()
        self.temp_memory: list[str] = []
        self.short_memory: list[str] = []  # 短期記憶(n=<7)
        self.long_memory: list[str] | None = None  # 長期記憶(from neo4j)

    # 短い文章で出力を返す（これ複数回で1回の返答）
    def streamchat(self, k: int, user_input: str | None = None, long_memory: list[str] | None = None, max_tokens: int = 240):
        # prompt
        system_prompt = """Output is Japanese.
                        Continue to your previous sentences.
                        Don't reveal hidden information."""
        if user_input is None:
            user_prompt = "continue it. If you can't continue, please type 'end'."  # より確実に、前の文章を継続するようにする。
        else:
            user_prompt = f"""{user_input}
            ----------------------------------------
            Chat history:
            {self.short_memory}
            ----------------------------------------
            """

        # long_memoryがある場合、それをuser_inputに追加する。
        if long_memory:
            self.long_memory = "\n".join(long_memory)

        if self.long_memory:
            user_prompt += (f"""
            ----------------------------------------
            Memory from Database:
            {self.long_memory}
            ----------------------------------------
            """)

        ai_prompt = "".join(self.temp_memory)  # 単純にこれまでの履歴を入れた場合、それに続けて生成される。
        logger.info(f"ai_prompt: {ai_prompt}")

        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
            assistant_message=ai_prompt,
        ).create_messages()  # 会話の記憶を追加

        # response生成
        response = self.client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
            max_tokens=max_tokens,  # 240をベースにする。初回のみ応答速度を上げるために、80で渡す。
            temperature=0.7,
            frequency_penalty=0.3,  # 繰り返しを抑制するために必須。
        )
        response_text = response.choices[0].message.content
        return response_text

    def closechat(self):
        # temp_memoryをshort_memoryに追加
        self.short_memory.extend("".join(self.temp_memory))

        # short_memoryが7個を超えたら、古いものから削除
        while len(self.short_memory) > 7:
            self.short_memory.pop(0)

        # temp_memoryとlong_memoryをリセット
        self.temp_memory = []
        self.long_memory = None

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

    # websocketに対応して、triplet, graphを送信する関数
    async def wb_get_graph_from_triplet(self, text: str, websocket: WebSocket):
        # run_sequenceを一時停止
        # result = await get_graph_from_triplet(text)
        result = None
        if result is None:
            return None
        triplet, graph = result
        # globalのnode_infosを更新し、wb_generate_audioで使えるようにする。
        self.long_memory = graph
        logger.info(f"triplet: {triplet}")
        logger.info(f"graph: {graph}")

    # テキスト生成から音声合成、再生までを統括する関数
    async def wb_generate_audio(
        self, input_data: WebSocketInputData, websocket: WebSocket, k: int = 4
    ):

        # historyと同じ内容かどうかを調べて、同じなら生成しないようにできるかもしれない。（function callingか）
        code_block = []
        inside_code_block = False

        for i in range(k):
            max_tokens = 80 if i == 0 else 240  # 初回のみ応答速度を上げるために、80で渡す。
            input_text = input_data.input_text if i == 0 else None  # 初回のみ受け取ったテキストを渡す。
            response = self.streamchat(
                k=k, user_input=input_text, max_tokens=max_tokens  # long_memory=self.long_memory
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

        results = "\n".join(self.temp_memory)
        logger.info(f"temp_memory: {self.temp_memory}")
        self.closechat()  # チャットを終了し、temp_memoryをshort_memoryに移す。
        return results


# Neo4jに保存
# theme、summary、entity
# summary 作成
# entity  作成
# full_text = {"User": input_text, "Ririse": responses}


# コードブロックテキストをWebSoketで送り返す。
async def handle_code_block(code_block_content, websocket: WebSocket):
    # ```の行を削除してから、フロントエンドに送る。
    # code = "\n".join(code_block_content)
    code = "\n".join(line for line in code_block_content if "```" not in line.strip())
    print(f"code: {code}")
    message = {"type": "code", "code": code}
    await websocket.send_text(json.dumps(message))


# 音声合成
async def _get_voice(text: str, websocket: WebSocket):
    text = text.replace(".", "、")  # 1. 2. のような箇条書きを、ポーズとして認識可能な1、2、に変換する。
    audio_path = await get_voice(text)
    # ここで音声合成を0.1 sec待てばエラーが出ないかもしれない
    if audio_path:
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        # バイナリデータをBase64エンコードしてJSONに格納
        encoded_audio = base64.b64encode(audio_data).decode("utf-8")
        message = {
            "type": "audio",
            "audioData": encoded_audio,
            "text": text,
        }  # ここに送りたいテキストをセット

        await websocket.send_text(json.dumps(message))  # JSONとして送信

        os.remove(audio_path)
