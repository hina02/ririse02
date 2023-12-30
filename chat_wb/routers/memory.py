from logging import getLogger
from chat_wb.neo4j.memory import (get_messages, get_titles, query_messages, create_and_update_title,
                                  get_latest_messages, get_latest_message_relationships)
from chat_wb.neo4j.triplet import TripletsConverter
from chat_wb.models import remove_suffix
from fastapi import APIRouter, Body
from chat_wb.neo4j.neo4j import get_node_relationships
from chat_wb.models import Node, Triplets, ShortMemory, TempMemory

memory_router = APIRouter()

# ロガー設定
logger = getLogger(__name__)


@memory_router.get("/get_messages", tags=["memory"])
def get_messages_api(title: str):
    return get_messages(title)


@memory_router.get("/get_titles", tags=["memory"])
def get_titles_api():
    return get_titles()


# [HACK] message由来のrelationshipsとuser_input_entity由来のrelationshipsを統合するという強引な構成
@memory_router.get("/get_latest_messages/{title}/{n}", tags=["memory"])
def get_latest_messages_api(title: str, n: int = 7) -> Triplets | None:
    # Title -> Message -> Entityを取得
    relationships = get_latest_message_relationships(title, n)

    # Message から user_input_entityに基づくrelationshipsを取得 Entity -> Entity
    messages, latest_node_id = get_latest_messages(title, n)
    """指定したタイトルの最新n件のメッセージを取得する"""
    message_nodes = []
    triplets = []
    if messages:
        for message in reversed(messages):
            message_node = Node(label="Message", name=message["user_input"], properties=message)
            message_nodes.append(message_node)

            # ShortMemory.convert_to_tripltets()を流用して、複数のuser_input_entityを一つのTripletsにまとめる
            triplets.append(
                TempMemory(
                    user_input=message["user_input"],
                    ai_response=message["ai_response"],
                    triplets=Triplets().model_validate_json(message.get("user_input_entity")) if message.get("user_input_entity") else None,
                )
            )
    short_memory = ShortMemory(short_memory=triplets, limit=n)
    short_memory.convert_to_tripltets()
    triplets_set = short_memory.triplets
    triplets_set.nodes.extend(message_nodes)
    # triplets_set.relationshipsに、relationshipsを追加し、setで重複を削除する
    triplets_set.relationships.extend(relationships)
    triplets_set.relationships = list(set(triplets_set.relationships))

    return triplets_set


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
