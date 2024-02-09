from datetime import datetime
from logging import getLogger

from neo4j import Transaction

from ..models import MessageNode, NodeHistory, TempMemory, Triplets, WebSocketInputData
from .base import Neo4jDataManager
from .index import Neo4jIndexManager
from .utils import (
    convert_neo4j_message_to_model,
    convert_neo4j_node_to_model,
    convert_neo4j_relationship_to_model,
    convert_neo4j_scene_to_model,
    get_embedding,
)

# ロガー設定
logger = getLogger(__name__)


class Neo4jMemoryService(Neo4jDataManager, Neo4jIndexManager):
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
            self.create_vector_index("Message")
            self.create_node_index("RANGE", "Message", "create_time")
            self.create_node_index("RANGE", "Scene", "create_time")
            self.create_node_index("Text", "Person", "name")
            self.create_relationship_index("RANGE", "CONTAIN", "create_time")
            # show index
            indices = self.show_index()
            return indices

    def get_messages(self, scene: str, n: int) -> list[MessageNode]:
        """Get the latest n messages by scene."""
        query = """
                MATCH (n:Scene {scene: $scene})-[:CONTAIN]->(m:Message)
                WITH m
                ORDER BY m.create_time DESC
                LIMIT $n
                RETURN m
                """
        params = {"scene": scene, "n": n}
        with self.driver.session() as session:
            result = session.run(query, params)
            messages = []
            for record in result:
                message = convert_neo4j_message_to_model(record["m"])
                messages.append(message) if message else None
        return messages

    def get_latest_messages(self, scene: str, n: int) -> Triplets | None:
        """Get the latest n messages by scene."""
        n = n - 1 if n > 1 else 1
        query = """
                MATCH (:Scene {{scene: $scene}})-[:CONTAIN]->(m:Message)
                WITH m
                ORDER BY m.create_time DESC
                LIMIT 1
                MATCH path = (m)-[:FOLLOW*0..{n}]->(m2:Message)
                WITH collect(path) AS paths, collect(m2) AS messages

                UNWIND paths AS p
                UNWIND relationships(p) AS rel
                WITH messages, paths, collect(DISTINCT rel) AS pathRelationships

                UNWIND messages AS message
                OPTIONAL MATCH (message)-[r:CONTAIN]->(n1)
                OPTIONAL MATCH (n1)-[r2]->(n2)

                WITH messages,
                    pathRelationships,
                    collect(DISTINCT n1) AS entity,
                    collect(DISTINCT r) AS r,
                    collect(DISTINCT r2) AS r2,
                    collect(DISTINCT n2) AS entity2
                WITH messages + entity + entity2 AS nodes,
                    pathRelationships + r + r2 AS relationships

                RETURN nodes, relationships
                """
        # WITH messages, pathRelationships, collect(DISTINCT n1) AS entity, collect(DISTINCT r) AS r, collect(DISTINCT r2) AS r2, collect(DISTINCT n2) AS entity2
        # WITH messages + entity + entity2 AS nodes, pathRelationships + r + r2 AS relationships
        params = {"scene": scene, "n": n}
        with self.driver.session() as session:
            result = session.run(query, params).single()
            nodes = set()
            relationships = set()
            # if result:
            for node in result["nodes"]:
                nodes.add(convert_neo4j_node_to_model(node))
            for relationship in result["relationships"]:
                relationships.add(convert_neo4j_relationship_to_model(relationship))
            return Triplets(nodes=nodes, relationships=relationships)

    def get_scenes(self) -> list[str]:
        """Get the list of scenes."""
        query = """
                MATCH (a:Scene)
                RETURN a
                """
        with self.driver.session() as session:
            results = session.run(query)
            scenes = [convert_neo4j_scene_to_model(record["a"]) for record in results]
        return scenes

    # [TODO] test
    def get_message_entities(self, node_ids: list[int]) -> list[TempMemory]:
        """Messageから、Entity -> Entityのノード、閉じたリレーションシップを取得する"""
        query = """
                UNWIND $node_ids AS node_id
                MATCH (m:Message)-[:CONTAIN]->(n)
                WHERE id(m) = node_id

                WITH m, collect(n) AS entity
                UNWIND entity as n1
                UNWIND entity as n2
                MATCH (n1)-[r]->(n2)

                WITH m, entity, collect(r) AS relationships
                RETURN collect({message: m, entity: entity, relationships: relationships}) AS result
                """
        with self.driver.session() as session:
            result = session.run(query, node_ids=node_ids)

            # TempMemory(MessageとTripletsの集合)に変換する。
            temp_memories: list[TempMemory] = []
            for record in result:
                for item in record["result"]:
                    message = convert_neo4j_message_to_model(item["message"])
                    # 各Messageに対するEntityとRelationshipsをTripletsに格納する。
                    entity = [convert_neo4j_node_to_model(e) for e in item["entity"]]
                    relationships = [convert_neo4j_relationship_to_model(r) for r in item["relationships"]]
                    if entity or relationships:
                        triplets = Triplets(nodes=entity, relationships=relationships)
                    else:
                        triplets = None

                    # TempMemoryを作成する
                    temp_memory = TempMemory(
                        message=message,
                        triplets=triplets,
                    )
                    temp_memories.append(temp_memory)
            return temp_memories

    # [TODO] test
    # [HACK] AI predictionでは、query_by_entityらしい。entity labelでベクター Indexも検討。
    def query_messages(self, query: str, k: int = 3, threshold: float = 0.9, time_threshold: int = 365) -> list[MessageNode]:
        """ベクトル検索(user_input -> user_input + ai_response)でMessageを検索する。"""
        vector = get_embedding(query)
        # queryNodes内で時間指定を行うことができないので、広めに取得してから、フィルタリングする。
        init_k = k * 10 if k * 10 < 100 else 100
        with self.driver.session() as session:
            result = session.run(
                """
                CALL db.index.vector.queryNodes('Message', $init_k, $vector)
                YIELD node, score
                WHERE score > $threshold AND node.create_time > datetime() - duration({days: $time_threshold})
                WITH node, score
                LIMIT $k
                RETURN node, score
                """,
                init_k=init_k,
                k=k,
                vector=vector,
                threshold=threshold,
                time_threshold=time_threshold,
            )

            messages = []
            for record in result:
                message = convert_neo4j_message_to_model(record["node"])
                if message:
                    score = round(record["score"], 6)
                    logger.info(f"score: {score} message: {message.user_input}")
                    messages.append(message) if message else None
        return messages

    def create_and_update_scene(self, scene: str, new_scene: str | None = None) -> bool:
        """Sceneノードを作成、更新する"""
        pa_vector = get_embedding(new_scene) if new_scene else get_embedding(scene)
        current_utc_datetime = datetime.utcnow()
        current_time = current_utc_datetime.isoformat() + "Z"
        query = """
                MERGE (a:Scene {scene: $scene})
                ON CREATE SET a.create_time = datetime($create_time), a.update_time = datetime($create_time), a.scene = $new_scene
                ON MATCH SET a.update_time = datetime($update_time), a.scene = $new_scene
                WITH a
                CALL db.create.setNodeVectorProperty(a, 'embedding', $vector)
                """
        params = {
            "scene": scene,
            "new_scene": new_scene if new_scene else scene,
            "create_time": current_time,
            "update_time": current_time,
            "vector": pa_vector,
        }
        with self.driver.session() as session:
            session.run(query, params)
            logger.info(f"Scene Node created: {scene}")

    # [TODO] test
    # store message
    def store_message(self, data: WebSocketInputData, ai_response: str, user_input_entity: Triplets | None = None) -> MessageNode:
        current_utc_datetime = datetime.utcnow()
        create_time = current_utc_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
        update_time = create_time

        with self.driver.session() as session:
            # transaction
            tx = session.begin_transaction()
            try:
                # create parent node
                parent_id = self.update_parent_node(tx, data.scene, create_time, update_time)
                # create message node
                message = self.create_message_node(tx, data, ai_response, user_input_entity, create_time)
                # create parent relationships
                self.create_parent_relationships(tx, message, parent_id)
                # create message relationships
                self.create_message_relationships(tx, message, data.former_node_id)
                # transaction commit
                tx.commit()

                # create entity relationships (outside of transaction)
                self.create_entity_relationships(message, user_input_entity)
            except Exception as e:
                tx.rollback()
                raise f"Store message failed: {e}"
            if message:
                return message

    # sub functions
    def update_parent_node(self, tx: Transaction, scene: str, create_time: str, update_time: str) -> int:
        """update parent node (Scene) of Message node."""
        query = """
                MERGE (a:Scene {scene: $scene})
                ON CREATE SET a.create_time = datetime($create_time), a.update_time = datetime($create_time)
                ON MATCH SET a.update_time = datetime($update_time)
                RETURN id(a) AS scene_id
                """
        params = {"scene": scene, "create_time": create_time, "update_time": update_time}
        record = tx.run(query, params).single()
        return record["scene_id"]

    def create_message_node(
        self, tx: Transaction, data: WebSocketInputData, ai_response: str, user_input_entity: Triplets | None, create_time: str
    ) -> MessageNode:
        embed_message = f"{data.source}: {data.user_input}\n {data.AI}: {data.ai_response}"
        vector = get_embedding(embed_message)  # user_input, ai_responseのセットを保存し、user_inputでqueryする想定

        query = """
                CREATE (b:Message {
                    create_time: datetime($create_time),
                    source: $source,
                    user_input: $user_input,
                    user_input_entity: $user_input_entity,
                    AI: $AI,
                    ai_response: $ai_response
                })
                WITH b
                CALL db.create.setNodeVectorProperty(b, 'embedding', $vector)
                RETURN b
                """
        params = {
            "create_time": create_time,
            "source": data.source,
            "user_input": data.user_input,
            "user_input_entity": user_input_entity.model_dump_json() if user_input_entity else None,
            "AI": data.AI,
            "ai_response": ai_response,
            "vector": vector,
        }
        record = tx.run(query, params).single()
        message = convert_neo4j_message_to_model(record["b"])
        logger.info(f"Message Node created. message_id: {message.id}")
        return message

    def create_parent_relationships(self, tx: Transaction, message: MessageNode, parent_id: int) -> None:
        """(a:Scene)-[CONTAIN]->(b:Message)"""
        query = """
                MATCH (a), (b)
                WHERE id(a) = $scene_id AND id(b) = $new_node_id
                CREATE (a)-[:CONTAIN]->(b)
                """
        params = {"scene_id": parent_id, "new_node_id": message.id}
        tx.run(query, params)

    def create_message_relationships(self, tx: Transaction, message: MessageNode, former_node_id: int | None) -> None:
        """(new:Message)-[:FOLLOW/PRECEDES]-(old:Message)"""
        if former_node_id is not None:
            query = """
                MATCH (b), (c)
                WHERE id(b) = $new_node_id AND id(c) = $former_node_id
                CREATE (b)-[:FOLLOW]->(c)
                CREATE (c)-[:PRECEDES]->(b)
                """
            params = {"new_node_id": message.id, "former_node_id": former_node_id}
            tx.run(query, params)

    def create_entity_relationships(self, message: MessageNode, user_input_entity: Triplets | None) -> None:
        """(new:Message)-[:CONTAIN]->(entity)"""
        if user_input_entity:
            with self.driver.session() as session:
                for node in user_input_entity.nodes:
                    properties = node.properties if node.properties is not None else {}
                    query = f"""
                    MATCH (b) WHERE id(b) = $new_node_id
                    MATCH (d:{node.label})
                    WHERE d.name = $name OR $name IN d.name_variation
                    CREATE (b)-[r:CONTAIN]->(d)
                    SET r = $props
                    RETURN id(d) as rel_id
                    """
                    params = {
                        "name": node.name,
                        "new_node_id": message.id,
                        "props": properties,
                    }
                    record = session.run(query, params).single()
                    rel_id = record.get("rel_id")
                    if rel_id is None:
                        logger.error(f"Relationship not created. (:Message)-[:CONTAIN]->({node.name}:{node.label})")

    async def pursue_node_update_history(self, label: str, name: str) -> NodeHistory | None:
        """get Message list: (entity)<-[r:CONTAIN]-(Message)
        r.properties contains updated entity node properties at that time.
        Then, this Message list is used to get node update history."""

        query = f"""
                MATCH (m:Message)-[r]->(n:{label})
                WHERE $name IN n.name_variation OR n.name = $name
                RETURN m, r, n
                """
        with self.driver.session() as session:
            result = session.run(query, name=name)

            node = None
            messages = []
            relationships = []
            for record in result:
                # Initial Node
                if node is None:
                    node = convert_neo4j_node_to_model(record["n"])

                if node is not None:
                    # Message Node
                    message = convert_neo4j_message_to_model(record["m"])
                    messages.append(message) if message else None
                    # Relationship
                    relationship = convert_neo4j_relationship_to_model(record["r"])
                    relationships.append(relationship) if relationship else None

        if node is not None:
            return NodeHistory(node=node, messages=messages, relationships=relationships)
