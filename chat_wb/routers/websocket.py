from fastapi import APIRouter, WebSocket, Body, Form, BackgroundTasks
from fastapi.responses import StreamingResponse
from logging import getLogger
import json
import asyncio
from chat_wb.main.wb import get_stream_chat_client, StreamChatClient
from chat_wb.models import WebSocketInputData, Triplets

logger = getLogger(__name__)

wb_router = APIRouter()


# websocketの設定
@wb_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # クライアントからのJSONメッセージを待つ
    data = await websocket.receive_text()
    input_data = WebSocketInputData.model_validate_json(data)
    with_voice = input_data.with_voice

    # StreamChatClientを取得（input_dataを渡し、ここで、user_inputの更新も行う）
    client: StreamChatClient = await get_stream_chat_client(input_data)

    # store_message用に、former_node_idを指定する。
    former_node_id = client.latest_message_id
    input_data.former_node_id = former_node_id

    # メイン処理    非同期タスクを開始
    get_memory_task = asyncio.create_task(client.wb_get_memory(websocket))       # messageをベクタークエリし、関連するnode, relationshipを取得
    store_memory_task = asyncio.create_task(client.wb_store_memory())   # user_input_entity, short_memory取得、保存

    # クエリの結果を待って、ストリーミングレスポンスを開始
    await get_memory_task
    if with_voice:
        await client.wb_generate_audio(websocket)  # レスポンス、音声合成
    else:
        await client.wb_generate_text(websocket)
    # エンティティ保存の完了を待つ
    await store_memory_task

    # After chat response and store entity, store Message to Neo4j and close chat (memory_turn_over).
    await client.store_message_and_close_chat(input_data)

    # websocketにshort_memory.triplets(nodes, relationshipsのset)を渡して、closeメッセージを送信する
    message = {"type": "close",
               "node_id": client.latest_message_id,
               "short_memory": client.short_memory.triplets.model_dump_json()}
    await websocket.send_text(json.dumps(message))

    # websocketを閉じる
    await websocket.close()


# websocketを使用しない設定
@wb_router.post("/chat", tags=["memory"])
async def chat_endpoint(
    background_tasks: BackgroundTasks,
    scene: str = Form(...),
    user: str = Form("彩澄しゅお"),
    AI: str = Form("彩澄りりせ"),
    user_input: str = Form(...),
):
    input_data = WebSocketInputData(
        scene=scene,
        user=user,
        AI=AI,
        source=user,
        user_input=user_input,
    )
    # StreamChatClientを取得（input_dataを渡し、ここで、user_inputの更新も行う）
    client = await get_stream_chat_client(input_data)
    # store_message用に、former_node_idを指定する。
    input_data.former_node_id = client.latest_message_id
    # メッセージを受信した後、非同期タスクを開始。
    get_memory_task = asyncio.create_task(client.wb_get_memory())
    store_memory_task = asyncio.create_task(client.wb_store_memory())

    # クエリの結果を待って、ストリーミングレスポンスを開始
    await get_memory_task
    response = StreamingResponse(client.generate_text(), media_type="text/plain")
    # エンティティ保存の完了を待つ
    await store_memory_task

    # After chat response and store entity, run background task
    background_tasks.add_task(background_task, input_data, client)

    return response


async def background_task(input_data: WebSocketInputData, client: StreamChatClient):
    """After chat response, store Message to Neo4j and close chat (memory_turn_over)."""
    await client.store_message_and_close_chat(input_data)  # memory_turn_overにより、一時的な要素をリセットする。
