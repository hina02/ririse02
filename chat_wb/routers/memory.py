# test API
from logging import getLogger
from chat_wb.neo4j.memory import store_to_neo4j, query_vector, get_messages, get_titles
from fastapi import APIRouter


memory_router = APIRouter()

# ロガー設定
logger = getLogger(__name__)


@memory_router.get("/store_to_neo4j", tags=["memory"])
async def store_to_neo4j_api(
    title: str, user_input: str, ai_response: str, former_node_id: int = None
):
    """フロントでtitleを呼び出した際に、最新メッセージのnode_idを返す。"""
    node_id = await store_to_neo4j(
        title=title,
        user_input=user_input,
        ai_response=ai_response,
        former_node_id=former_node_id,
    )
    return node_id


@memory_router.get("/query_vector", tags=["memory"])
def query_vector_api(query: str, label: str, k: int = 3):
    return query_vector(query, label, k)


@memory_router.get("/get_messages", tags=["memory"])
def get_messages_api(title: str):
    return get_messages(title)


@memory_router.get("/get_titles", tags=["memory"])
def get_titles_api():
    return get_titles()
