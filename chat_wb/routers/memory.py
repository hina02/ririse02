from logging import getLogger
from chat_wb.neo4j.memory import (get_messages, get_titles, query_messages, create_and_update_title,
                                  get_message_entities, pursue_node_update_history)
from chat_wb.neo4j.triplet import TripletsConverter
from chat_wb.models import remove_suffix
from fastapi import APIRouter, Body
from chat_wb.neo4j.neo4j import get_node_relationships
from chat_wb.models import Triplets, ShortMemory

memory_router = APIRouter()

# ロガー設定
logger = getLogger(__name__)


@memory_router.get("/get_messages", tags=["memory"])
def get_messages_api(title: str, n: int = 100):
    messages = get_messages(title, n)
    return messages


@memory_router.get("/get_titles", tags=["memory"])
def get_titles_api():
    return get_titles()


# [TODO] MessageからのContainリレーションシップを作成する
@memory_router.get("/get_latest_messages/{title}/{n}", tags=["memory"])
def get_latest_messages_api(title: str, n: int = 7) -> Triplets | None:
    """指定したタイトルの最新n件のメッセージを取得し、関連するEntityと閉じたリレーションシップを取得する。"""
    # 指定したタイトルの最新n件のメッセージを取得する
    messages = get_messages(title, n)

    # Messageからlist[TempMemory]を取得する
    if messages:
        node_ids = [message.id for message in messages]
        short_memory = get_message_entities(node_ids)

        # list[TempMemory]のentityを集約したTripletsを返す
        short_memory = ShortMemory(short_memory=short_memory, limit=n)
        return short_memory.convert_to_tripltets()


@memory_router.post("/store_memory_from_triplet", tags=["memory"])
async def store_memory_from_triplet_api(text: str):
    converter = TripletsConverter()
    triplets = await converter.run_sequences(text)
    return await converter.store_memory_from_triplet(triplets)


@memory_router.post("/create_and_update_title", tags=["memory"])
async def create_and_update_title_api(title: str = Body(...), new_title: str | None = Body(None)):
    return await create_and_update_title(title, new_title)


@memory_router.get("/retrieve_entity", tags=["memory"])
async def retrieve_entity_api(text: str):
    """ラベル無しでnameのみから、一次リレーションまでとノードプロパティを得る。"""
    user_input_entity = await TripletsConverter().extract_entites(text)
    entities = []
    for entity in user_input_entity:
        entities.append(remove_suffix(entity))
    return await get_node_relationships(names=entities)


@memory_router.get("/query_messages", tags=["memory"])
async def query_messages_api(query: str):
    return await query_messages(query)


@memory_router.get("/pursue_node_update_history", tags=["memory"])
async def pursue_node_update_history_api(label: str, name: str):
    return await pursue_node_update_history(label, name)
