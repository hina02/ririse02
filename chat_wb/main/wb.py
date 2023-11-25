import os
import json
from logging import getLogger
import base64
from fastapi import WebSocket
from chat_wb.voice.text2voice import playVoicePeak
from chat_wb.main.chat import streamchain, TextFormatter
from chat_wb.neo4j.triplet import get_graph_from_triplet
from chat_wb.models.wb import WebSocketInputData

logger = getLogger(__name__)

# テキスト整形
formatter = TextFormatter()


# 音声合成して、wavファイルのfilepathを返す
async def get_voice(text: str):
    file_path = await playVoicePeak(script=text, narrator="Asumi Ririse")

    if not file_path:
        return {
            "status": "queued",
            "message": "Your request is queued. Please check back later.",
        }
    return file_path


node_infos = None


# websocketに対応して、triplet, graphを送信する関数
async def wb_get_graph_from_triplet(text: str, websocket: WebSocket):
    # run_sequenceを一時停止
    # result = await get_graph_from_triplet(text)
    result = None
    if result is None:
        return None
    triplet, graph = result
    # globalのnode_infosを更新し、wb_generate_audioで使えるようにする。
    global node_infos
    node_infos = graph
    node_infos = "ボイスロイド has 彩澄しゅお, 彩澄りりせ"
    logger.info(f"triplet: {triplet}")
    logger.info(f"graph: {graph}")


# テキスト生成から音声合成、再生までを統括する関数
async def wb_generate_audio(input_data: WebSocketInputData, websocket: WebSocket, k: int = 4):
    # テキスト生成
    chain = streamchain(k)
    formatter = TextFormatter()

    # historyと同じ内容かどうかを調べて、同じなら生成しないようにできるかもしれない。（function callingか）
    responses = []
    code_block = []
    inside_code_block = False

    # 受け取ったデータ
    input_text = input_data.input_text

    for i in range(k):
        response = await chain.arun(
            input=input_text,  # graph=node_infos
        )  # ここにentityを入れれば、global変数が変更されたタイミングで、適用される。

        # テキストを正規表現で分割してリストに整形
        formatted_text = formatter.format_text(response)

        # """を含むコードブロックの確認
        for text in formatted_text:
            if '```' in text:
                if not inside_code_block:  # Starting a new code block
                    inside_code_block = True
                    code_block.append(text)
                else:  # Ending an existing code block
                    inside_code_block = False
                    code_block.append(text)
                    await handle_code_block(code_block, websocket)
                    code_block = []
                continue

            if inside_code_block:  # If inside a code block, just append the text to code_block
                code_block.append(text)
                continue

            # 既にテキストが存在するかどうかを確認し、繰り返しレスポンスになっている場合、そこで中断する。
            if text in responses:
                results = "\n".join(responses)
                return results
            else:
                # print(f"text: {text}")
                responses.append(text)
                await _get_voice(text, websocket)

    # print(chain.memory.load_memory_variables("chat_history"))
    results = "\n".join(responses)
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
    code = "\n".join(line for line in code_block_content if '```' not in line.strip())
    print(f"code: {code}")
    message = {
        "type": "code",
        "code": code
    }
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
