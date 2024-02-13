from datetime import datetime
from logging import getLogger
from typing import Union

from neo4j import Transaction

from ...models import DocumentNode, MessageNode, SceneNode, TopicNode
from ..utils import convert_neo4j_system_node_to_model, get_embedding

# ロガー設定
logger = getLogger(__name__)


class Neo4jSystemNodeManager:
    """Neo4jEntityManagerの関数と区別するため、すべてsystemを関数につける。"""

    # query embedding
    async def query_system_nodes(
        self, query: str, label: str, k: int = 3, threshold: float = 0.8, time_threshold: int = 365
    ) -> list[Union[SceneNode, TopicNode, MessageNode, DocumentNode]]:
        vector = get_embedding(query)
        query = f"""
                CALL db.index.vector.queryNodes({label}, $k, $vector)
                YIELD node, score
                WHERE score > $threshold AND node.timestamp > datetime() - duration({{days: $time_threshold}})
                WITH node, apoc.map.removeKeys(properties(node), ['embedding']) AS filteredNode
                RETURN filteredNode
                """
        params = {
            "k": k,
            "vector": vector,
            "threshold": threshold,
            "time_threshold": time_threshold,
        }
        result = await self.execute_read(query, params)
        nodes = [convert_neo4j_system_node_to_model(label, record) async for record in result]
        return nodes

    # get
    async def get_system_node(
        self, tx: Transaction, label: str, timestamp: str
    ) -> Union[SceneNode, TopicNode, MessageNode, DocumentNode, None]:
        """指定したsystemnodeを返す。"""
        query = f"""
                MATCH (n:{label}{{timestamp:$timestamp}})
                WITH n, apoc.map.removeKeys(properties(n), ['embedding']) AS node
                RETURN node
                """
        params = {"timestamp": timestamp}
        result = await tx.run(query, params)
        record = await result.single()
        return convert_neo4j_system_node_to_model(label, record) if record else None

    async def get_topics(self, tx: Transaction, label: str, timestamp: str) -> list[TopicNode]:
        """指定したScene/Documentの、Topicのリストを返す。"""
        query = f"""
                MATCH (n:{label} {{timestamp: $timestamp}})-[:CONTAIN]->(t:Topic)
                WITH t, apoc.map.removeKeys(properties(t), ['embedding']) AS topic
                RETURN topic
                """
        params = {"timestamp": timestamp}
        result = await tx.run(query, params)
        nodes = [convert_neo4j_system_node_to_model("Topic", record) async for record in result]
        return nodes

    async def get_messages(self, tx: Transaction, timestamp: str) -> list[MessageNode]:
        """指定したTopicの、Messageのリストを返す。"""
        query = """
                MATCH (n:Scene {timestamp: $timestamp})-[:CONTAIN]->(m:Message)
                WITH m, apoc.map.removeKeys(properties(m), ['embedding']) AS message
                RETURN message
                """
        params = {"timestamp": timestamp}
        result = await tx.run(query, params)
        nodes = [convert_neo4j_system_node_to_model("Message", record) async for record in result]
        return nodes

    # create / update
    async def create_system_node(self, tx: Transaction, node: Union[SceneNode, TopicNode, DocumentNode]) -> None:
        current_utc_datetime = datetime.utcnow()
        timestamp = current_utc_datetime.isoformat() + "Z"
        query = f"""
                CREATE (n:{node.label} {{timestamp: $timestamp, $properties}})
                """
        params = {
            "timestamp": timestamp,
            "properties": node.properties,
        }
        await tx.run(query, params)

    async def end_system_node(self, tx: Transaction, node: Union[SceneNode, TopicNode, DocumentNode]) -> None:
        """Scene/Topicを終了し、summary、vectorを追加する。"""
        # [TODO] summaryを追加するロジック
        summary = ""
        vector = get_embedding(summary)
        query = f"""
                MATCH (n:{node.label} {{timestamp: $timestamp}})
                SET (n.end_time = datetime($end_time), n.summary = $summary)
                WITH n
                CALL db.create.setNodeVectorProperty(n, 'embedding', $vector)
                """
        params = {
            "timestamp": node.timestamp,
            "summary": node.summary,
            "vector": vector,
        }
        await tx.run(query, params)
