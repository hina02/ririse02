from logging import getLogger

from neo4j import AsyncDriver

from ..models import Node, Relationship, Triplets
from .utils import convert_neo4j_node_to_model, convert_neo4j_relationship_to_model

# ロガー設定
logger = getLogger(__name__)


class Neo4jDataManager:
    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    # Node
    async def get_node(self, node: Node) -> Node | None:
        "Scene, Messageを除く、指定したラベルのノードを取得する。"
        query = f"""
                MATCH (n:{node.label})
                WHERE n.name = $name OR $name IN n.name_variation
                RETURN n
                """
        params = {"name": node.name}

        async with self.driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()
            return convert_neo4j_node_to_model(record["n"]) if record else None

    async def create_update_node(self, node: Node) -> int | None:
        result = self.get_node(node)
        if result:
            # [HACK] label, nameが一意であることを前提とする
            if node.properties:
                await self.update_node(result, node.properties)  # match node and new properties
                logger.info(f"Updated node {result.to_cypher()}")
            else:
                pass
        else:
            node = await self.create_node(node)
            logger.info(f"Created node {node.to_cypher()}")

    async def update_node(self, node: Node, properties: dict[str, list[str]]) -> None:
        """if node and properties, append node properties without overwrite."""
        properties.pop("name", None)
        for key, new_values in properties.items():
            if key not in node.properties:
                node.properties[key] = new_values
            else:
                new_list = node.properties[key] + new_values
                node.properties[key] = list(set(new_list))
        node.properties["name"] = node.name  # name is always unique string
        # [TODO] ここで取り出したnodeをフロントロジックに回せる。（リスト内の相反する値のチェック等）

        query = """
                MATCH (n)
                WHERE id(n) = $node_id
                SET n = $properties
                """
        params = {"node_id": node.id, "properties": node.properties}

        async with self.driver.session() as session:
            session.run(query, params)

    async def create_node(self, node: Node):
        """if no node, create node."""
        node.properties["name"] = node.name
        query = f"""
                MERGE (n:{node.label} {{name: $name}})
                ON CREATE SET n = $properties
                """
        params = {"name": node.name, "properties": node.properties}

        async with self.driver.session() as session:
            session.run(query, params)

    async def delete_node(self, node: Node):
        """priority: id > label and name."""
        if node.id:
            delete_query = """
                MATCH (n)
                WHERE id(n) = $node_id
                DETACH DELETE n
                RETURN count(n) as count
                """
            params = {"node_id": node.id}
        else:
            delete_query = f"""
                MATCH (n:{node.label} {{name: $name}})
                DETACH DELETE n
                RETURN count(n) as count
                """
            params = {"name": node.name}

        async with self.driver.session() as session:
            result = await session.run(delete_query, params)
            record = await result.single()
            count = record.get("count")
            logger.info(f"{count} node deleted.")

    # Relationship
    # [HACK]ノードが増えてレスポンスが遅くなるようなら、一つのnameを受け取るクエリの非同期処理を検討する。
    async def get_node_relationships(self, names: list[str], depth: int = 1) -> Triplets | None:
        query = f"""
                MATCH (start)
                WHERE start.name IN $names
                    OR ANY(name_variation IN start.name_variation WHERE name_variation IN $names)

                WITH collect(start) as starts
                UNWIND starts as start
                    OPTIONAL MATCH path = (start)-[r*1..{depth}]-(end)
                    WHERE NONE(node IN nodes(path) WHERE 'Message' IN labels(node) OR 'Scene' IN labels(node))

                UNWIND r as rel
                RETURN starts,
                    collect(distinct startNode(rel)) as start_nodes,
                    collect(distinct endNode(rel)) as end_nodes,
                    collect(distinct rel) as rels
                """
        params = {"names": names, "depth": depth}

        async with self.driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()

            nodes = set()
            if record:
                # クエリ探索の最初のノードの情報
                initial_nodes = [convert_neo4j_node_to_model(node) for node in record["starts"]]
                # relationshipsのstart_node, end_node, relsをモデルに変換
                start_nodes = [convert_neo4j_node_to_model(node) for node in record["start_nodes"]]
                end_nodes = [convert_neo4j_node_to_model(node) for node in record["end_nodes"]]
                relationships = [convert_neo4j_relationship_to_model(relationship) for relationship in record["rels"]]
                # ノードを統合
                nodes = set(initial_nodes + start_nodes + end_nodes)
                triplets = Triplets(nodes=nodes, relationships=relationships)
                return triplets

    async def get_node_relationships_between(self, node1: Node, node2: Node) -> list[Relationship]:
        query = f"""
                MATCH (a:{node1.label})-[r]-(b:{node2.label})
                WHERE ($name1 IN a.name_variation OR a.name = $name1)
                    AND ($name2 IN b.name_variation OR b.name = $name2)
                RETURN a, r, b
                """
        params = {"name1": node1.name, "name2": node2.name}

        async with self.driver.session() as session:
            result = await session.run(query, params)
            values = await result.values("r")
            relationships = [convert_neo4j_relationship_to_model(value) for value in values]
            return relationships

    async def create_update_relationship(self, relationship: Relationship) -> None:
        # search existing nodes and relationships
        query_node1 = Node(label=relationship.start_node_label, name=relationship.start_node, properties={})
        query_node2 = Node(label=relationship.end_node_label, name=relationship.end_node, properties={})
        rels = await self.get_node_relationships_between(query_node1, query_node2)
        match = False
        # check if relationship type is already exist
        for rel in rels:
            if rel.type == relationship.type and rel.start_node == relationship.start_node and rel.end_node == relationship.end_node:
                relationship.id = rel.id
                match = True
                break
        # if match relationship type, update properties
        if match:
            if relationship.properties:
                await self.update_relationship(relationship)
                logger.info(f"Relationship {relationship.to_cypher()} updated.")

        # if not match, create new relationship
        else:
            # relsが空の場合、node1, node2が存在しない可能性があるため、作成する
            node1 = await self.create_node(query_node1)
            node2 = await self.create_node(query_node2)
            # create new relationship with node_id
            result = await self.create_relationship(node1.id, node2.id, relationship)
            logger.info(f"Relationship {result.to_cypher()} created.")

    async def update_relationship(self, relationship: Relationship) -> None:
        # [TODO] Node同様にlist追加型を検討
        query = """
                MATCH ()-[r]->()
                WHERE id(r) = $relationship_id
                SET r += $properties
                """
        params = {"relationship_id": relationship.id, "properties": relationship.properties}

        with self.driver.session() as session:
            session.run(query, params)

    async def create_relationship(self, node1_id: int, node2_id: int, relationship: Relationship) -> Relationship:
        query = f"""
                MATCH (a), (b)
                WHERE id(a) = $node1_id AND id(b) = $node2_id
                CREATE (a)-[r:{relationship.type}]->(b)
                SET r = $properties
                return a, r, b
                """
        params = {"node1_id": node1_id, "node2_id": node2_id, "properties": relationship.properties}

        with self.driver.session() as session:
            record = session.run(query, params).single()
            return convert_neo4j_relationship_to_model(record["r"])

    async def delete_relationship(self, relationship: Relationship) -> None:
        query = """
                MATCH ()-[r]->()
                WHERE id(r) = $relationship_id
                DELETE r
                """
        params = {"relationship_id": relationship.id}
        with self.driver.session() as session:
            session.run(query, params)
            logger.info(f"Relationship {relationship.to_cypher()} deleted.")
