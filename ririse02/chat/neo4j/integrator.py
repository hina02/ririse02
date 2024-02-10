from logging import getLogger

from neo4j import Transaction

from ..models import Node
from .base import Neo4jDataManager

# ロガー設定
logger = getLogger(__name__)


# Integrate name variations of two nodes
class Neo4jNodeIntegrator(Neo4jDataManager):

    async def integrate_nodes(self, node1: Node, node2: Node) -> None:
        """Integrate 2 nodes by name variations, properties, and relationships to node1. For secure, separate the delete process."""
        # check nodes exist
        async with self.driver.session(database=self.database) as session:
            matched_node1 = await session.execute_read(self.get_node, node1)
            matched_node2 = await session.execute_read(self.get_node, node2)

            if not matched_node1 or not matched_node2:
                logger.info(
                    f"Node {None if matched_node1 else node1.to_cypher()} {None if matched_node2 else node2.to_cypher()} does not exist."
                )
                return
            node1 = matched_node1
            node2 = matched_node2

            # main process
            name_variation = await session.execute_write(self.integrate_node_names, node1, node2)
            node1.properties["name_variation"] = name_variation
            logger.info(f"Integrated node name variation: {name_variation}")

            properties = await session.execute_write(self.integrate_node_properties, node1, node2)
            logger.info(f"Integrated node properties: {properties}")

            await session.execute_write(self.integrate_relationships, node1, node2)
            logger.info("Integrated node relationships")

    async def integrate_node_names(self, tx: Transaction, node1: Node, node2: Node) -> list[str]:
        """Integrate name and name variations of 2 nodes to node1."""
        query = f"""
                MATCH (n1:{node1.label}{{name: $name1}}), (n2:{node2.label}{{name: $name2}})
                SET n1.name_variation = CASE
                    WHEN n1.name_variation IS NULL AND n2.name_variation IS NULL THEN [n2.name]
                    WHEN n1.name_variation IS NULL THEN apoc.coll.toSet([n2.name] + n2.name_variation)
                    WHEN n2.name_variation IS NULL THEN apoc.coll.toSet(n1.name_variation + [n2.name])
                    ELSE apoc.coll.toSet(n1.name_variation + [n2.name] + n2.name_variation)
                END
                RETURN n1.name_variation AS name_variation
                """
        params = {"name1": node1.name, "name2": node2.name}
        result = await tx.run(query, params)
        record = await result.single()
        return record["name_variation"]

    async def integrate_node_properties(self, tx: Transaction, node1: Node, node2: Node) -> dict[str, list[str]]:
        """Integrate properties of 2 nodes to node1."""
        props1 = node1.properties
        props2 = node2.properties

        # Integrate the same key values into list
        for key in set(props1.keys()).union(props2.keys()):
            if key != "name":  # skip 'name' property
                if key in props1 and key in props2:
                    props1[key] = list(set(props1[key] + props2[key]))  # merge and deduplicate
                elif key in props2:
                    props1[key] = props2[key]  # key only exists in props2
        props1["name"] = node1.name  # add name as string

        query = f"""
                MATCH (n1:{node1.label}{{name: $name}})
                SET n1 = $props
                RETURN properties(n1) AS properties
                """
        params = {"name": node1.name, "props": props1}

        result = await tx.run(query, params)
        record = await result.single()
        return record["properties"]

    async def integrate_relationships(self, tx: Transaction, node1: Node, node2: Node) -> None:
        """Integrate relationships of 2 nodes to node1."""
        query1 = f"""
                MATCH (n2:{node2.label}{{name:$name2}})-[r]->(m)
                MATCH (n1:{node1.label}{{name:$name1}})
                CALL apoc.refactor.from(r, n1)
                YIELD input, output
                RETURN output
                """
        query2 = f"""
                MATCH (n2:{node2.label}{{name:$name2}})<-[r]-(m)
                MATCH (n1:{node1.label}{{name:$name1}})
                CALL apoc.refactor.to(r, n1)
                YIELD input, output
                RETURN output
                """
        params = {"name1": node1.name, "name2": node2.name}
        await tx.run(query1, params)
        await tx.run(query2, params)
