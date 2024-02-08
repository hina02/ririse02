import os
from neo4j import GraphDatabase, Driver
from .base import Neo4jDataManager
from .cache import Neo4jCacheManager
from .index import Neo4jIndexManager
from .integrator import Neo4jNodeIntegrator
from .memory import Neo4jMemoryService

USER_CONFIG_MAP = {
    "local": {
        "uri": os.environ["NEO4J_URI"],
        "username": "neo4j",
        "password": os.environ["NEO4J_PASSWORD"]
    },
    "aura": {
        "uri": os.environ["NEO4J_AURA_URI"],
        "username": "neo4j",
        "password": os.environ["NEO4J_AURA_PASSWORD"]
    }
}


class Neo4jDriverManager:
    # [TODO] ユーザーごとの接続情報を取得する
    connection_cache = {}

    @classmethod
    def get_connection(cls, user_id: str) -> Driver:
        config = USER_CONFIG_MAP.get(user_id)
        if config:
            # 接続キーを(config["uri"], config["username"])のタプルとして作成
            connection_key = (config["uri"], config["username"])
            # キャッシュに接続が存在しない場合は新たに作成
            if connection_key not in cls.connection_cache:
                cls.connection_cache[connection_key] = GraphDatabase.driver(
                    config["uri"], auth=(config["username"], config["password"]))
            return cls.connection_cache[connection_key]
        else:
            raise Exception("Database configuration not found for user_id: {}".format(user_id))

    # データベース接続情報を選択し、Neo4jDataManagerインスタンスを生成する依存性関数
    # [TODO] user_id: Optional[str] = Header(None) でユーザーIDを取得する
    @classmethod
    def get_neo4j_data_manager(cls, user_id: str = "local") -> Neo4jDataManager:
        driver = cls.get_connection(user_id)
        return Neo4jDataManager(driver)

    @classmethod
    def get_neo4j_cache_manager(cls, user_id: str = "local") -> Neo4jCacheManager:
        driver = cls.get_connection(user_id)
        return Neo4jCacheManager(driver)

    @classmethod
    def get_neo4j_node_integrator(cls, user_id: str = "local") -> Neo4jNodeIntegrator:
        driver = cls.get_connection(user_id)
        return Neo4jNodeIntegrator(driver)

    @classmethod
    def get_neo4j_memory_service(cls, user_id: str = "local") -> Neo4jMemoryService:
        driver = cls.get_connection(user_id)
        return Neo4jMemoryService(driver)

    @classmethod
    def get_neo4j_index_manager(cls, user_id: str = "local") -> Neo4jIndexManager:
        driver = cls.get_connection(user_id)
        return Neo4jIndexManager(driver)
