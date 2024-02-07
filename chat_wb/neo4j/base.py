from logging import getLogger
from neo4j import Driver
from ..models import Node, Relationship, Triplets
from .utils import convert_neo4j_node_to_model, convert_neo4j_relationship_to_model

# ロガー設定
logger = getLogger(__name__)


class Neo4jDataManager():
    def __init__(self, driver: Driver):
        self.driver = driver

# Node
    def get_node(self, node: Node) -> list[Node]:
        "Title, Messageを除く、指定したラベルのノードを取得する。"
        query = f"""
                MATCH (n:{node.label})
                WHERE n.name = $name OR $name IN n.name_variation
                RETURN n
                """
        params = {"name": node.name}

        with self.driver.session() as session:
            result = session.run(query, params)

            nodes = [convert_neo4j_node_to_model(record["n"]) for record in result]
            return nodes

    def create_update_node(self, node: Node) -> int | None:
        result = self.get_node(node)
        if result:
            # [HACK] label, nameが一意であることを前提とする
            if node.properties:
                self.update_node(result[0], node.properties)  # match node and new properties
                logger.info(f"Updated node {result[0].to_cypher()}")
            else:
                pass
        else:
            node = self.create_node(node)
            logger.info(f"Created node with id {node.id}")
            return node.id

    def update_node(self, node: Node, properties: dict[str, list[str]]) -> None:
        """if node and properties, append node properties without overwrite."""
        properties.pop("name", None)
        for key, new_values in properties.items():
            if key not in node.properties:
                node.properties[key] = new_values
            else:
                new_list = node.properties[key] + new_values
                node.properties[key] = list(set(new_list))
        node.properties["name"] = node.name     # name is always unique string
        # [TODO] ここで取り出したnodeをフロントロジックに回せる。（リスト内の相反する値のチェック等）

        query = """
                MATCH (n)
                WHERE id(n) = $node_id
                SET n = $properties
                """
        params = {"node_id": node.id, "properties": node.properties}

        with self.driver.session() as session:
            session.run(query, params)

    def create_node(self, node: Node) -> Node:
        """if no node, create node."""
        node.properties["name"] = node.name
        query = f"""
                MERGE (n:{node.label} {{name: $name}})
                ON CREATE SET n = $properties
                RETURN id(n) as node_id
                """
        params = {"name": node.name, "properties": node.properties}

        with self.driver.session() as session:
            result = session.run(query, params).single()
            node.id = result["node_id"]
            return node

    def delete_node(self, node: Node):
        """priority: id > label and name."""
        if node.id:
            match_query = """
                MATCH (n)
                WHERE id(n) = $node_id
                RETURN count(n) as count
                """
            delete_query = """
                MATCH (n)
                WHERE id(n) = $node_id
                DETACH DELETE n
                RETURN count(n) as count
                """
            params = {"node_id": node.id}
        else:
            match_query = f"""
                MATCH (n:{node.label} {{name: $name}})
                RETURN count(n) as count
                """
            delete_query = f"""
                MATCH (n:{node.label} {{name: $name}})
                DETACH DELETE n
                RETURN count(n) as count
                """
            params = {"name": node.name}

        with self.driver.session() as session:
            before_count = session.run(match_query, params).single().get("count")
            if before_count == 0:
                logger.info(f"Node {node.to_cypher()} not found.")
            else:
                after_count = session.run(delete_query, params).single().get("count")
                logger.info(f"{before_count} nodes matched and {before_count - after_count} nodes deleted.")

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
                    WHERE NONE(node IN nodes(path) WHERE 'Message' IN labels(node) OR 'Title' IN labels(node))

                UNWIND r as rel
                RETURN starts,
                    collect(distinct startNode(rel)) as start_nodes,
                    collect(distinct endNode(rel)) as end_nodes,
                    collect(distinct rel) as rels
                """
        params = {"names": names, "depth": depth}

        with self.driver.session() as session:
            record = session.run(query, params).single()

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

    async def get_node_relationships_between(self, node1: Node, node2: Node) -> (
            Node | None, Node | None, list[Relationship]):
        query = f"""
                MATCH (a:{node1.label})-[r]-(b:{node2.label})
                WHERE ($name1 IN a.name_variation OR a.name = $name1)
                    AND ($name2 IN b.name_variation OR b.name = $name2)
                RETURN a as node1, b as node2, r
                """
        params = {"name1": node1.name, "name2": node2.name}

        with self.driver.session() as session:
            result = session.run(query, params)

            # nodeもrelationshipもmatchしない場合、None, None, []が返る
            node1 = None
            node2 = None
            relationships = []
            for record in result:
                node1 = convert_neo4j_node_to_model(record["node1"])
                node2 = convert_neo4j_node_to_model(record["node2"])
                relation = convert_neo4j_relationship_to_model(record["r"])
                relationships.append(relation)
            return node1, node2, relationships

    async def create_update_relationship(self, relationship: Relationship) -> None:
        # search existing nodes and relationships
        query_node1 = Node(label=relationship.start_node_label, name=relationship.start_node, properties={})
        query_node2 = Node(label=relationship.end_node_label, name=relationship.end_node, properties={})
        node1, node2, rels = await self.get_node_relationships_between(query_node1, query_node2)
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
            # if node1 is None, create new node1
            if node1 is None:
                node1 = self.create_node(query_node1)
            # if node2 is None, create new node2
            if node2 is None:
                node2 = self.create_node(query_node2)
            # create new relationship with node_id
            await self.create_relationship(node1.id, node2.id, relationship)
            logger.info(f"Relationship {relationship.to_cypher()} created.")

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

    async def create_relationship(self, node1_id: int, node2_id: int, relationship: Relationship) -> None:
        query = f"""
                MATCH (a), (b)
                WHERE id(a) = $node1_id AND id(b) = $node2_id
                CREATE (a)-[r:{relationship.type}]->(b)
                SET r = $properties
                """
        params = {
            "node1_id": node1_id,
            "node2_id": node2_id,
            "properties": relationship.properties
        }

        with self.driver.session() as session:
            session.run(query, params)

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
