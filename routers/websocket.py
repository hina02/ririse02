from fastapi import APIRouter, WebSocket
import json
import asyncio
from chat.wb import wb_generate_audio, wb_get_graph_from_triplet
from chat.memory import get_messages, store_to_neo4j
from chat.wb import WebSocketInputData

wb_router = APIRouter()


# websocketの設定
@wb_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()  # 接続を受け入れる

    # クライアントからのJSONメッセージを待つ
    data = await websocket.receive_text()
    print(data)
    input_data = WebSocketInputData(**json.loads(data))
    input_text = input_data.input_text
    title = input_data.title
    messages = get_messages(title)
    former_node_id = messages[-1].get("id") if messages else None
    input_data.former_node_id = former_node_id

    # メッセージを受信した後、generate_audioを呼び出す
    results = await asyncio.gather(
        wb_generate_audio(input_data, websocket, 6),  # レスポンス、音声合成
        wb_get_graph_from_triplet(input_text, websocket),  # triplet, graph（ノード情報）獲得
    )

    # 全ての処理が終了した後で、Neo4jに保存してwebsocketを閉じる
    await store_to_neo4j(input_data, results[0])   # websocket終了時に、Neo4jに保存
    await websocket.close()  # websocketを閉じる
