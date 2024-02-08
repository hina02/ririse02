from logging import getLogger
from fastapi import APIRouter, Body, Depends, HTTPException
from chat_wb.neo4j import Neo4jDriverManager as driver, Neo4jMemoryService, TripletsConverter
from chat_wb.models import remove_suffix
from chat_wb.models import Triplets, ShortMemory, Relationship

memory_router = APIRouter()

# ロガー設定
logger = getLogger(__name__)
# def get_node_labels(cache: Neo4jCacheManager = Depends(driver.get_neo4j_cache_manager)) -> list[str]:


@memory_router.get("/get_messages", tags=["message"])
def get_messages(scene: str, n: int = 100,
                 db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.get_messages(scene, n)


@memory_router.get("/get_scenes", tags=["scene"])
def get_scenes(db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.get_scenes()


# [TODO] MessageからのContainリレーションシップを作成する
@memory_router.get("/get_latest_messages/{scene}/{n}", tags=["message"])
def get_latest_messages(scene: str, n: int = 7,
                        db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)) -> Triplets | None:
    """指定したタイトルの最新n件のメッセージを取得し、関連するEntityと閉じたリレーションシップを取得する。"""
    return db.get_latest_messages(scene, n)


@memory_router.post("/store_memory_from_triplet", tags=["triplet"])
async def store_memory_from_triplet(text: str):
    converter = TripletsConverter()
    triplets = await converter.run_sequences(text)
    return await converter.store_memory_from_triplet(triplets)


@memory_router.post("/create_and_update_scene", tags=["scene"])
def create_and_update_scene(scene: str, new_scene: str | None = None,
                            db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.create_and_update_scene(scene, new_scene)


@memory_router.get("/retrieve_entity", tags=["message"])
async def retrieve_entity(text: str,
                          db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    """ラベル無しでnameのみから、一次リレーションまでとノードプロパティを得る。"""
    user_input_entity = await TripletsConverter().extract_entites(text)
    logger.info(f"user_input_entity: {user_input_entity}")
    entities = []
    for entity in user_input_entity:
        entities.append(remove_suffix(entity))
    return await db.get_node_relationships(names=entities)


@memory_router.get("/query_messages", tags=["message"])
async def query_messages(query: str,
                         db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return await db.query_messages(query)


@memory_router.get("/pursue_node_update_history", tags=["message"])
async def pursue_node_update_history(label: str, name: str,
                                     db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return await db.pursue_node_update_history(label, name)


# show index
@memory_router.get("/show_index", tags=["index"])
def show_index(type: str | None = None,
               db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.show_index(type)

# check index
@memory_router.get("/check_index", tags=["index"])
def check_index(db: Neo4jMemoryService = Depends(driver.get_neo4j_memory_service)):
    return db.check_index()
