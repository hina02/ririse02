from fastapi import APIRouter, WebSocket, Depends
import json
import asyncio
from chat_wb.main.wb import StreamChatClient, get_stream_chat_client
from chat_wb.neo4j.memory import get_messages, store_message
from chat_wb.models.wb import WebSocketInputData

wb_router = APIRouter()


# websocketの設定
@wb_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()  # 接続を受け入れる
    # クライアントからのJSONメッセージを待つ
    data = await websocket.receive_text()
    input_data = WebSocketInputData(**json.loads(data))
    input_text = input_data.input_text
    title = input_data.title

    # StreamChatClientを取得
    client = get_stream_chat_client(title, input_text)
    messages = get_messages(title)
    former_node_id = messages[-1].get("id") if messages else None   # 最新のメッセージのidを取得
    input_data.former_node_id = former_node_id

    # メッセージを受信した後、generate_audioを呼び出す
    await asyncio.gather(
        client.wb_generate_audio(input_text, websocket, 3),  # レスポンス、音声合成
        client.wb_get_memory_from_triplet(websocket),  # triplet, graph（ノード情報）獲得
    )

    # 全ての処理が終了した後で、Neo4jに保存し、保存したノードのidを返す。
    new_node_id = await store_message(
        input_data=input_data,
        ai_response=client.temp_memory,
        user_input_entity=client.user_input_entity)
    message = {"type": "node_id", "node_id": new_node_id}
    await websocket.send_text(json.dumps(message))

    # チャットを終了し、temp_memoryをshort_memoryに移す。
    client.closechat()

    # websocketを閉じる
    await websocket.close()
