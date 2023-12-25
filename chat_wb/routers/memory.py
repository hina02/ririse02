# test API
from logging import getLogger
from chat_wb.neo4j.memory import query_vector, get_messages, get_titles, create_and_update_title
from chat_wb.neo4j.triplet import TripletsConverter
from chat_wb.models import Node
from fastapi import APIRouter


memory_router = APIRouter()

# ロガー設定
logger = getLogger(__name__)


@memory_router.get("/query_vector", tags=["memory"])
def query_vector_api(query: str, label: str, k: int = 3):
    return query_vector(query, label, k)


@memory_router.get("/get_messages", tags=["memory"])
def get_messages_api(title: str):
    return get_messages(title)


@memory_router.get("/get_titles", tags=["memory"])
def get_titles_api():
    return get_titles()


@memory_router.get("/get_memory_from_triplet", tags=["memory"])
async def get_memory_from_triplet_api(text: str, AI: str = "彩澄りりせ", user: str = "彩澄しゅお", depth: int = 1):
    converter = TripletsConverter()
    triplets = await converter.run_sequences(text)
    return await converter.get_memory_from_triplet(triplets, AI, user, depth)


@memory_router.post("/store_memory_from_triplet", tags=["memory"])
async def store_memory_from_triplet_api(text: str):
    converter = TripletsConverter()
    triplets = await converter.run_sequences(text)
    return await converter.store_memory_from_triplet(triplets)


@memory_router.post("/create_and_update_title", tags=["memory"])
async def create_and_update_title_api(title: str, new_title: str | None = None):
    return await create_and_update_title(title, new_title)
