from logging import getLogger
from chat_wb.models import Node, Relationship
from .base import Neo4jDataManager
from .utils import convert_neo4j_relationship_to_model

# ロガー設定
logger = getLogger(__name__)


# Integrate name variations of two nodes
class Neo4jNodeIntegrator(Neo4jDataManager):

    def integrate_nodes(self, node1: Node, node2: Node):
        """Integrate 2 nodes by name variations, properties, and relationships to node1. For secure, separate the delete process."""
        # check nodes exist
        match_nodes1 = self.get_node(node1)
        node1 = match_nodes1[0] if match_nodes1 else None
        match_nodes2 = self.get_node(node2)
        node2 = match_nodes2[0] if match_nodes2 else None
        if not node1 or not node2:
            logger.info(f"Node {{{node1.label}:{node1.name}}} or {{{node2.label}:{node2.name}}} not found.")
            return

        # main process
        name_variation = self.integrate_node_names(node1, node2)
        logger.info(f"Integrated node1 name variation: {name_variation}")
        properties = self.integrate_node_properties(node1, node2)
        logger.info(f"Integrated node1 properties: {properties}")
        relationships = self.integrate_relationships(node1, node2)
        logger.info(f"Integrated node1 relationships: {relationships}")

    def integrate_node_names(self, node1: Node, node2: Node) -> list[str]:
        """Integrate name and name variations of 2 nodes to node1."""
        query = """
                MATCH (n1), (n2)
                WHERE id(n1) = $node1_id AND id(n2) = $node2_id
                SET n1.name_variation = CASE
                    WHEN n1.name_variation IS NULL AND n2.name_variation IS NULL THEN [n1.name, n2.name]
                    WHEN n1.name_variation IS NULL THEN apoc.coll.toSet([n1.name, n2.name] + n2.name_variation)
                    WHEN n2.name_variation IS NULL THEN apoc.coll.toSet(n1.name_variation + [n1.name, n2.name])
                    ELSE apoc.coll.toSet(n1.name_variation + [n1.name, n2.name] + n2.name_variation)
                END
                RETURN properties(n1) AS properties
                """
        params = {"node1_id": node1.id, "node2_id": node2.id}
        with self.driver.session() as session:
            result = session.run(query, params).single()
            return result["properties"].get("name_variation")

    def integrate_node_properties(self, node1: Node, node2: Node) -> dict[str, list[str]]:
        """Integrate properties of 2 nodes to node1."""
        props1 = node1.properties
        props2 = node2.properties
        print(f"props1: {props1}")
        print(f"props2: {props2}")
        # Integrate the same key values into list
        for key in set(props1.keys()).union(props2.keys()):
            if key != "name":  # skip 'name' property
                if key in props1 and key in props2:
                    props1[key] = list(set(props1[key] + props2[key]))  # merge and deduplicate
                elif key in props2:
                    props1[key] = props2[key]   # key only exists in props2
        props1["name"] = node1.name  # keep the original name
        print(f"props1: {props1}")
        query = """
                MATCH (n1)
                WHERE id(n1) = $node1_id
                SET n1 = $props
                RETURN properties(n1) AS properties
                """
        params = {"node1_id": node1.id, "props": props1}

        with self.driver.session() as session:
            result = session.run(query, params).single()
            return result["properties"]

    def integrate_relationships(self, node1: Node, node2: Node) -> list[Relationship]:
        """Integrate relationships of 2 nodes to node1."""
        query = """
                MATCH (n2)-[r]->(m)
                WHERE id(n2) = $node2_id
                MATCH (n1)
                WHERE id(n1) = $node1_id
                CALL apoc.refactor.from(r, n1)
                YIELD input, output
                RETURN input, output
                """
        params = {"node1_id": node1.id, "node2_id": node2.id}
        with self.driver.session() as session:
            result1 = session.run(query, params)
            relationships1 = [convert_neo4j_relationship_to_model(record["output"]) for record in result1]

        query = """
                MATCH (n2)<-[r]-(m)
                WHERE id(n2) = $node2_id
                MATCH (n1)
                WHERE id(n1) = $node1_id
                CALL apoc.refactor.to(r, n1)
                YIELD input, output
                RETURN input, output
                """
        with self.driver.session() as session:
            result2 = session.run(query, params)
            relationships2 = [convert_neo4j_relationship_to_model(record["output"]) for record in result2]
            return relationships1 + relationships2
