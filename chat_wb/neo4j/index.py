from logging import getLogger
from neo4j import Driver
from ..models import Neo4jIndex
from .utils import normalize_key
from enum import Enum

# ロガー設定
logger = getLogger(__name__)


class IndexType(Enum):
    RANGE = 'RANGE'
    TEXT = 'TEXT'
    POINT = 'POINT'
    VECTOR = 'VECTOR'


class Neo4jIndexManager:
    def __init__(self, driver: Driver):
        self.driver = driver

    def show_index(self, type: IndexType | None) -> list[str]:
        """Show Neo4j vector and return index name list.
           type = ['RANGE', 'TEXT', 'POINT', 'VECTOR']"""  # 'FULLTEXT'は未対応
        partial_query = """
                SHOW INDEXES
                YIELD name, type, labelsOrTypes, properties, options
                """
        query = f"{partial_query} WHERE type = '{type}'" if type else partial_query

        with self.driver.session() as session:
            results = session.run(query)
            response = [Neo4jIndex(**result) for result in results]
            return response

    # [TODO]ノード数が一定以上のラベルに対してインデックスを作成する関数を検討
    def create_node_index(self, type: IndexType, label: str, property: str):
        """Create Neo4j vector index. type = ['RANGE', 'TEXT', 'POINT']"""
        if type == "VECTOR":
            return self.create_vector_index(label)

        label = normalize_key(label)    # ラベル名を正規化（特殊文字を削除）
        property = normalize_key(property)

        # main process
        index = f"{label}_{property}"
        query = f"""
                CREATE {type} INDEX {index} IF NOT EXISTS
                FOR (n:{label})
                ON (n.{property})
                """
        params = {"label": label, "property": property}
        with self.driver.session() as session:
            session.run(query, params)
            logger.info(f"Node index created: {index}")

    def create_relationship_index(self, type: IndexType, label: str, property: str):
        """Create Neo4j vector index. type = ['RANGE', 'TEXT', 'POINT']"""
        label = normalize_key(label)    # ラベル名を正規化（特殊文字を削除）
        property = normalize_key(property)

        index = f"{label}_{property}"
        query = f"""
                CREATE {type} INDEX {index} IF NOT EXISTS
                FOR ()-[r:{label}]-()
                ON (r.{property})
                """
        params = {"label": label, "property": property}
        with self.driver.session() as session:
            session.run(query, params)
            logger.info(f"Relationship index created: {index}")

    def create_vector_index(self, label: str):
        query = """
                CALL db.index.vector.createNodeIndex(
                $index, $label, 'embedding', 1536, 'cosine')
                """
        index = f"{label}_embedding"
        params = {"index": index, "label": label}
        with self.driver.session() as session:
            session.run(query, params)
            logger.info(f"Vector Index created: {index}")

    def drop_index(self, name: str):
        """Delete Neo4j index."""
        query = f"DROP INDEX {name} IF EXISTS"
        with self.driver.session() as session:
            session.run(query)
            logger.info(f"Index dropped: {name}")
