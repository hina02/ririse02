from logging import getLogger

from fastapi import APIRouter, Depends

from ...models import Triplets
from ..driver import Neo4jDriverManager as driver
from ..driver import Neo4jIndexManager, Neo4jMessageManager

memory_router = APIRouter()

# ロガー設定
logger = getLogger(__name__)


@memory_router.get("/get_messages", tags=["message"])
async def get_messages(scene: str, n: int = 100, db: Neo4jMessageManager = Depends(driver.get_neo4j_message_manager)):
    async with db.driver.session(database=db.database) as session:
        # execute transaction
        result = await session.execute_read(db.get_messages, scene, n)
    return result


@memory_router.get("/get_scenes", tags=["message"])
async def get_scenes(db: Neo4jMessageManager = Depends(driver.get_neo4j_message_manager)):
    return await db.get_scenes()


# [TODO] MessageからのContainリレーションシップを作成する
@memory_router.get("/get_latest_messages/{scene}/{n}", tags=["message"])
async def get_latest_messages(
    scene: str, n: int = 7, db: Neo4jMessageManager = Depends(driver.get_neo4j_message_manager)
) -> Triplets | None:
    """指定したタイトルの最新n件のメッセージを取得し、関連するEntityと閉じたリレーションシップを取得する。"""
    return await db.get_latest_messages(scene, n)


# get_message_entities
@memory_router.get("/get_message_entities", tags=["message"])
async def get_message_entities(
    scene: str, n: int = 100, db: Neo4jMessageManager = Depends(driver.get_neo4j_message_manager)
):
    return await db.get_message_entities(scene, n)


@memory_router.post("/create_and_update_scene", tags=["message"])
async def create_and_update_scene(
    scene: str, new_scene: str | None = None, db: Neo4jMessageManager = Depends(driver.get_neo4j_message_manager)
):
    return await db.create_and_update_scene(scene, new_scene)


@memory_router.get("/query_messages", tags=["message"])
async def query_messages(query: str, db: Neo4jMessageManager = Depends(driver.get_neo4j_message_manager)):
    return await db.query_messages(query)


@memory_router.get("/pursue_node_update_history", tags=["message"])
async def pursue_node_update_history(
    label: str, name: str, db: Neo4jMessageManager = Depends(driver.get_neo4j_message_manager)
):
    return await db.pursue_node_update_history(label, name)


# show index
@memory_router.get("/show_index", tags=["index"])
async def show_index(type: str | None = None, db: Neo4jIndexManager = Depends(driver.get_neo4j_index_manager)):
    return await db.show_index(type)


# check index
@memory_router.get("/check_index", tags=["index"])
def check_index(db: Neo4jIndexManager = Depends(driver.get_neo4j_index_manager)):
    return db.check_index()
