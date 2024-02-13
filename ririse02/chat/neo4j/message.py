import asyncio
from datetime import datetime
from logging import getLogger

from neo4j import Transaction

from ..models import (
    MessageEntityHolder,
    MessageNode,
    Node,
    NodeHistory,
    SceneNode,
    Triplets,
)
from .entity.entity import Neo4jEntityManager
from .system.system import Neo4jSystemNodeManager
from .utils import (
    convert_neo4j_node_to_model,
    convert_neo4j_relationship_to_model,
    convert_neo4j_system_node_to_model,
)

logger = getLogger(__name__)


# Message
class Neo4jMessageManager(Neo4jEntityManager, Neo4jSystemNodeManager):
    # Store Message
    async def store_message(
        self, scene: SceneNode, speaker: str, message: str, triplets: Triplets | None = None
    ) -> MessageEntityHolder:
        current_utc_datetime = datetime.utcnow()
        timestamp = current_utc_datetime.isoformat() + "Z"
        listener = (scene.participants.remove(speaker),)
        message_node = MessageNode(speaker=speaker, listener=listener, message=message, timestamp=timestamp)

        async with self.driver.session(database=self.database) as session:
            nodes = await session.execute_write(self.store_entity_from_triplet, triplets)
            await session.execute_write(self.create_message_node, scene, message_node)
            await session.execute_write(self.create_message_entity_relationships, message_node)

        return MessageEntityHolder(message=message_node, entities=nodes)

    async def store_entity_from_triplet(self, triplets: Triplets) -> list[Node]:
        """tripltetに基づいて、Neo4jにノード、リレーションシップを保存"""
        # update node
        print(f"triplets.nodes: {triplets.nodes}")
        update_tasks = [self.create_update_node(node) for node in triplets.nodes]
        updated_nodes = await asyncio.gather(*update_tasks)

        # update relationship
        print(f"triplets.relationships: {triplets.relationships}")
        if triplets.relationships:
            for relation in triplets.relationships:
                asyncio.create_task(self.create_update_relationship(relation))

        return updated_nodes

    async def create_message_node(self, tx: Transaction, scene: SceneNode, message: MessageNode) -> None:
        """
        1. create message node
        2. create relationships between message and scene
        3. create relationships between message and message
        4. create relationships between message and speaker
        5. create relationships between message and listener

        # [TODO] Scene作成時に、Scene、Speaker、Listenerのノードを作成する。
        # [TODO] SceneにSpeaker、Listenerを追加する際に、Speaker、Listenerのノードが存在しない場合は作成する。
        """
        query = """
                CREATE (m1:Message $message))
                WITH m1
                CALL db.create.setNodeVectorProperty(m1, 'embedding', $vector)
                MATCH (s:Scene {scene: $scene})
                CREATE  (s)-[:CONTAIN]->(m1)

                WITH s as scene, m1
                OPTIONAL MATCH (scene)-[:CONTAIN]->(m0:Message)
                WHERE NOT EXISTS { (m0)-[:RESPOND]->(:Message) }
                CREATE (m0)-[:RESPOND]->(m1)

                WITH m1
                MATCH (speaker:Person {name: $speaker})
                CREATE (speaker)-[:SPEAKER]->(m1)

                WITH m1
                UNWIND $listenerNames AS listenerName
                MATCH (listener:Person {name: listenerName})
                CREATE (message)-[:LISTENER]->(m1)
                """
        params = {
            "message": message.model_dump(),
            "scene": scene.scene,
            "speaker": message.source,
            "listenerNames": message.listener,
        }
        await tx.run(query, params)

    async def create_message_entity_relationships(self, tx: Transaction, message: MessageNode) -> [Node]:
        """Parallel transaction. Because label is static, cannot UNWIND entity.labels. in single transaction."""
        triplets = message.triplets
        exact_nodes = []
        if triplets:
            async with self.driver.session(database=self.database) as session:
                async for node in triplets.nodes:
                    exact_node = await session.execute_write(
                        self.create_message_entity_relationship, message.timestamp, node
                    )
                    exact_nodes.append(exact_node)
        return exact_nodes

    async def create_message_entity_relationship(self, tx: Transaction, timestamp: str, node: Node) -> Node:
        """(new:Message)-[:CONTAIN]->(entity)"""
        query = f"""
                MATCH (m:Message{{timestamp: $timestamp}}),
                      (n:{node.label})
                WHERE n.name = $name OR $name IN n.name_variation
                CREATE (m)-[r:CONTAIN]->(n)
                SET r = $props
                RETURN n
                """
        params = {
            "timestamp": timestamp,
            "name": node.name,
            "props": node.properties,  # 更新された分のノードプロパティを渡す。
        }
        result = await tx.run(query, params)
        record = await result.single()
        return convert_neo4j_node_to_model(record["d"])

    # Query Message
    async def get_messages(self, tx: Transaction, timestamp: str, n: int) -> list[MessageNode]:
        """Get the messages in topic.
        ここで取得するのは、message relationship (RESPOND n hops以内)    # そのtopicの最新n件のメッセージを取得する。
        (message timestamp DESC (最新n件) は、Short Memoryに蓄積されている)
        [TODO] どのような条件でメッセージを取得するかを検討する。
        """
        query = """
                MATCH (n:Scene {timestamp: $timestamp})-[:CONTAIN]->(m:Message)
                WITH m, apoc.map.removeKeys(properties(m), ['embedding'])
                ORDER BY m.timestamp DESC
                LIMIT $n
                """
        params = {"timestamp": timestamp, "n": n}
        result = await tx.run(query, params)
        messages = [convert_neo4j_system_node_to_model("Message", record["m"]) async for record in result]
        return messages

    async def pursue_node_update_history(self, label: str, name: str) -> NodeHistory | None:
        """get Message list: (entity)<-[r:CONTAIN]-(Message)
        r.properties contains updated entity node properties at that time.
        Then, this Message list is used to get node update history."""

        query = f"""
                MATCH (m:Message)-[r]->(n:{label})
                WHERE $name IN n.name_variation OR n.name = $name
                WITH m, apoc.map.removeKeys(properties(m), ['embedding'])

                RETURN m, r, n
                """
        async with self.driver.session(database=self.database) as session:
            result = await session.run(query, name=name)

            node = None
            messages = []
            relationships = []
            for record in result:
                # Initial Node
                if node is None:
                    node = convert_neo4j_node_to_model(record["n"])

                if node is not None:
                    # Message Node
                    message = convert_neo4j_system_node_to_model("Message", record["m"])
                    messages.append(message) if message else None
                    # Relationship
                    relationship = convert_neo4j_relationship_to_model(record["r"])
                    relationships.append(relationship) if relationship else None

        if node is not None:
            return NodeHistory(node=node, messages=messages, relationships=relationships)
