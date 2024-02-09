from datetime import datetime
from logging import getLogger

from neo4j import AsyncDriver, Transaction

from ..models import Node, Relationship, Triplets
from .utils import convert_neo4j_node_to_model, convert_neo4j_relationship_to_model

# ロガー設定
logger = getLogger(__name__)


class Neo4jDataManager:
    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    # Node
    async def get_node(self, tx: Transaction, node: Node) -> Node | None:
        """Scene, Messageを除く、指定したラベルのノードを取得する。
        他のクエリと組み合わせて使用されることが多いため、transactionとして作成。"""
        query = f"""
                MATCH (n:{node.label})
                WHERE n.name = $name OR $name IN n.name_variation
                RETURN n
                """
        params = {"name": node.name}

        result = await tx.run(query, params)
        record = await result.single()
        return convert_neo4j_node_to_model(record["n"]) if record else None

    async def create_update_node(self, node: Node) -> None:
        async with self.driver.session() as session:
            # transaction
            tx = await session.begin_transaction()
            try:
                result = await self.get_node(tx, node)
                if result:
                    # [HACK] label, nameが一意であることを前提とする
                    # merge on matchの形式では、propertiesの複雑な処理が不可能なため、クエリを分割
                    if node.properties:
                        await self.update_node(tx, result, node.properties)  # match node and new properties
                        logger.info(f"Updated node {result.to_cypher()}")
                    else:
                        pass
                else:
                    await self.create_node(tx, node)
                    logger.info(f"Created node {node.to_cypher()}")

                await tx.commit()
            except Exception as e:
                logger.error(e)
                tx.rollback()

    async def update_node(self, tx: Transaction, node: Node, properties: dict[str, list[str]]) -> None:
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

        query = f"""
                MATCH (n:{node.label} {{name: $name}})
                SET n += $properties
                """
        params = {"name": node.name, "properties": node.properties}
        await tx.run(query, params)

    async def create_node(self, tx: Transaction, node: Node):
        """create node."""
        node.properties["name"] = node.name
        query = f"CREATE (n:{node.label} $properties)"
        params = {"name": node.name, "properties": node.properties}
        logger.info(f"Created node {node.to_cypher()}")
        await tx.run(query, params)

    async def merge_node(self, tx: Transaction, node: Node) -> Node | None:
        """merge node."""
        query = f"""
                MERGE (n:{node.label} {{name: $name}})
                ON CREATE SET n += $properties
                RETURN n
                """
        params = {"name": node.name, "properties": node.properties}
        result = await tx.run(query, params)
        record = await result.single()
        return convert_neo4j_node_to_model(record["n"]) if record else None

    async def delete_node(self, node: Node):
        query = f"""
                MATCH (n:{node.label} {{name: $name}})
                DETACH DELETE n
                RETURN count(n) as count
                """
        params = {"name": node.name}

        async with self.driver.session() as session:
            result = await session.run(query, params)
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
        start = datetime.now()
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
                print(f"get_node_relationships: {datetime.now() - start}")
                return triplets

    async def get_node_relationships_between(self, tx: Transaction, node1: Node, node2: Node) -> list[Relationship]:
        query = f"""
                MATCH (a:{node1.label})-[r]-(b:{node2.label})
                WHERE ($name1 IN a.name_variation OR a.name = $name1)
                    AND ($name2 IN b.name_variation OR b.name = $name2)
                RETURN a, r, b
                """
        params = {"name1": node1.name, "name2": node2.name}
        relationships = []
        # transaction
        result = await tx.run(query, params)
        async for record in result:
            relationship = convert_neo4j_relationship_to_model(record["r"])
            if relationship:
                relationships.append(relationship)
        return relationships

    async def match_relationship(self, tx: Transaction, relationship: Relationship) -> Relationship | None:
        """check if relationship exists and return it."""
        query = f"""
                MATCH (a:{relationship.start_node_label})-[r:{relationship.type}]->(b:{relationship.end_node_label})
                WHERE ($name1 IN a.name_variation OR a.name = $name1)
                    AND ($name2 IN b.name_variation OR b.name = $name2)
                RETURN a, r, b
                """
        params = {"name1": relationship.start_node, "name2": relationship.end_node}
        # transaction
        result = await tx.run(query, params)
        record = await result.single()
        return convert_neo4j_relationship_to_model(record["r"]) if record else None

    async def create_update_relationship(self, relationship: Relationship) -> None:
        """[HACK] 各条件のクエリ回数
        relation type match : ①match ②update
        relation type match no property : ①match
        relation type not match : ①between ②merge relationship
        """
        async with self.driver.session() as session:
            # transaction
            tx = await session.begin_transaction()
            try:
                match = await self.match_relationship(tx, relationship)
                # if match, update properties
                if match:
                    if relationship.properties:
                        await self.update_relationship(tx, relationship)
                        logger.info(f"Relationship {relationship.to_cypher()} updated.")
                    else:
                        pass
                # if not match, create new relationship
                else:
                    await self.create_relationship(tx, relationship)
                    logger.info(f"Relationship {relationship.to_cypher()} created.")

                await tx.commit()
            except Exception as e:
                logger.error(e)
                tx.rollback()

    async def update_relationship(self, tx: Transaction, relationship: Relationship) -> None:
        # [TODO] Node同様にlist追加型を検討
        query = """
                MATCH ()-[r]->()
                WHERE id(r) = $relationship_id
                SET r += $properties
                """
        params = {"relationship_id": relationship.id, "properties": relationship.properties}
        await tx.run(query, params)

    async def create_relationship(self, tx: Transaction, relationship: Relationship):
        query = f"""
                MATCH (a:{relationship.start_node_label}), (b:{relationship.end_node_label})
                WHERE ($name1 IN a.name_variation OR a.name = $name1) AND ($name2 IN b.name_variation OR b.name = $name2)
                MERGE (a)-[r:{relationship.type}]->(b)
                ON CREATE SET r = $properties
                """
        params = {"name1": relationship.start_node, "name2": relationship.end_node, "properties": relationship.properties}

        await tx.run(query, params)

    async def delete_relationship(self, relationship: Relationship) -> None:
        query = f"""
                MATCH (a:{relationship.start_node_label})-[r:{relationship.type}]->(b:{relationship.end_node_label})
                WHERE ($name1 IN a.name_variation OR a.name = $name1) AND ($name2 IN b.name_variation OR b.name = $name2)
                DELETE r
                RETURN count(r) as count
                """
        params = {"name1": relationship.start_node, "name2": relationship.end_node}
        async with self.driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()
            count = record.get("count")
            logger.info(f"{count} node deleted.")  # delete時点のcount数であって、実際に削除された数ではない。
