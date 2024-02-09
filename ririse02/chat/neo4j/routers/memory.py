from logging import getLogger

from fastapi import APIRouter, Depends

from ...models import Triplets
from ..driver import Neo4jDriverManager as driver
from ..driver import Neo4jMemoryService

memory_router = APIRouter()

# ロガー設定
logger = getLogger(__name__)


@memory_router.get("/get_messages", tags=["message"])
def get_messages(scene: str, n: int = 100, db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.get_messages(scene, n)


@memory_router.get("/get_scenes", tags=["scene"])
def get_scenes(db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.get_scenes()


# [TODO] MessageからのContainリレーションシップを作成する
@memory_router.get("/get_latest_messages/{scene}/{n}", tags=["message"])
def get_latest_messages(scene: str, n: int = 7, db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)) -> Triplets | None:
    """指定したタイトルの最新n件のメッセージを取得し、関連するEntityと閉じたリレーションシップを取得する。"""
    return db.get_latest_messages(scene, n)


@memory_router.post("/create_and_update_scene", tags=["scene"])
def create_and_update_scene(scene: str, new_scene: str | None = None, db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.create_and_update_scene(scene, new_scene)


@memory_router.get("/query_messages", tags=["message"])
async def query_messages(query: str, db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return await db.query_messages(query)


@memory_router.get("/pursue_node_update_history", tags=["message"])
async def pursue_node_update_history(label: str, name: str, db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return await db.pursue_node_update_history(label, name)


# show index
@memory_router.get("/show_index", tags=["index"])
def show_index(type: str | None = None, db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.show_index(type)


# check index
@memory_router.get("/check_index", tags=["index"])
def check_index(db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.check_index()
