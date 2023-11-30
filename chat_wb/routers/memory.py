# test API
from logging import getLogger
from chat_wb.neo4j.memory import query_vector, get_messages, get_titles
from chat_wb.neo4j.triplet import run_sequences, get_memory_from_triplet, store_memory_from_triplet
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
async def get_memory_from_triplet_api(text: str):
    triplets = await run_sequences(text)
    return await get_memory_from_triplet(triplets)


@memory_router.get("/store_memory_from_triplet", tags=["memory"])
async def store_memory_from_triplet_api(text: str):
    triplets = await run_sequences(text)
    return store_memory_from_triplet(triplets)