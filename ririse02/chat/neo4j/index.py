from enum import Enum
from logging import getLogger

from neo4j import Driver

from ..models import Neo4jIndex
from .utils import normalize_key

# ロガー設定
logger = getLogger(__name__)


class IndexType(Enum):
    RANGE = "RANGE"
    TEXT = "TEXT"
    POINT = "POINT"
    VECTOR = "VECTOR"


# [TODO] 一部のindex(Person.name)を、CONSTRAINTに変更する。
class Neo4jIndexManager:
    def __init__(self, driver: Driver, database: str = "neo4j"):
        self.driver = driver
        self.database = database

    # Check main logic index and create if not exists.
    # [TODO]　初期ロジックとして、これを呼び出して実行する。（どこにするかは検討）
    def check_index(self) -> list[str]:
        """Check Neo4j vector index and create index if not exists."""
        vector_index = self.show_index(type="VECTOR")
        if vector_index:
            return vector_index
        else:
            # create main logic indices
            self.create_vector_index("Scene")
            self.create_vector_index("Document")
            self.create_vector_index("Topic")
            self.create_vector_index("Message")
            self.create_node_index("RANGE", "Message", "create_time")
            self.create_node_index("RANGE", "Scene", "create_time")
            self.create_node_index("Text", "Person", "name")
            self.create_node_index("Text", "Person", "name_variation")
            self.create_relationship_index("RANGE", "CONTAIN", "create_time")
            # show index
            indices = self.show_index()
            return indices

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

        label = normalize_key(label)  # ラベル名を正規化（特殊文字を削除）
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
        label = normalize_key(label)  # ラベル名を正規化（特殊文字を削除）
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
