from fastapi import APIRouter, WebSocket, Body
from logging import getLogger
import json
import asyncio
from chat_wb.main.wb import get_stream_chat_client
from chat_wb.neo4j.memory import get_messages, store_message
from chat_wb.models import WebSocketInputData, Triplets

logger = getLogger(__name__)

wb_router = APIRouter()


# websocketの設定
@wb_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()  # 接続を受け入れる
    # クライアントからのJSONメッセージを待つ
    data = await websocket.receive_text()
    input_data = WebSocketInputData.model_validate_json(data)
    with_voice = input_data.with_voice

    # StreamChatClientを取得（input_dataを渡し、ここで、user_inputの更新も行う）
    client = await get_stream_chat_client(input_data)

    # store_message用に、former_node_idを指定する。
    former_node_id = client.latest_message_id
    input_data.former_node_id = former_node_id

    # メイン処理
    if with_voice:
        await asyncio.gather(
            client.wb_generate_audio(websocket),  # レスポンス、音声合成
            client.wb_get_memory(websocket),  # messageをベクタークエリし、関連するnode, relationshipを取得
            client.wb_store_memory(),  # user_input_entity, short_memory取得、保存
        )
    else:
        await asyncio.gather(
            client.wb_generate_text(websocket),  # レスポンスのみ
            client.wb_get_memory(websocket),    # messageをベクタークエリし、関連するnode, relationshipを取得
            client.wb_store_memory(),  # user_input_entity, short_memory取得、保存
        )

    # 全ての処理が終了した後で、Neo4jに保存する。
    message = await store_message(
        input_data=input_data,
        ai_response=client.ai_response,
        user_input_entity=client.user_input_entity)

    # 最新のメッセージのidを更新
    client.latest_message_id = message.id

    # memory_turn_overにより、Messageとretrieval_memoryをshort_memoryに格納し、一時的な要素をリセットする。
    client.close_chat(message)

    # websocketにshort_memory.triplets(nodes, relationshipsのset)を渡して、closeメッセージを送信する
    message = {"type": "close",
               "node_id": message.id,
               "short_memory": client.short_memory.triplets.model_dump_json()}
    await websocket.send_text(json.dumps(message))

    # websocketを閉じる
    await websocket.close()
