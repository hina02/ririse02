from diskcache import Cache
from neo4j import Driver
from ..models import Node, Relationship


class Neo4jCacheManager:
    """Manage cache data and direct database access for Neo4j."""
    def __init__(self, driver: Driver, cache_dir="./cache"):
        self.driver = driver
        self.cache = Cache(directory=cache_dir)
        self.expire = 86400  # 1day = 86400sec

    def get_node_labels(self) -> list[str]:
        labels = self.cache.get("labels")
        if labels is None:
            # if not in cache, get from database
            with self.driver.session() as session:
                result = session.run("CALL db.labels()")
                labels = [record["label"] for record in result]
                # store in cache
                self.cache.set("labels", labels, expire=self.expire)
        return labels

    def get_node_names(self, label: str) -> list[str]:
        # error handling
        if label == "Title" or label == "Message":
            return []

        # main process
        node_names = self.cache.get(f"node_names_{label}")
        query = f"""
                MATCH (n:{label})
                RETURN n.name as name
                """
        if node_names is None:
            with self.driver.session() as session:
                result = session.run(query)
                node_names = [record["name"] for record in result]
                self.cache.set(f"node_names_{label}", node_names, expire=self.expire)
        return node_names

    def get_relationship_types(self) -> list[str]:
        relationship_types = self.cache.get("relationships_types")
        if relationship_types is None:
            with self.driver.session() as session:
                result = session.run("CALL db.relationshipTypes()")
                relationship_types = [record["relationshipType"] for record in result]
                self.cache.set("relationships_types", relationship_types, expire=self.expire)
        return relationship_types

    def get_label_and_relationship_type_sets(self) -> dict[tuple[str, str], str] | None:
        sets = self.cache.get("label_and_relationship_type_sets")
        query = """
                MATCH (n)-[r]->(m)
                RETURN labels(n) AS NodeLabels, type(r) AS RelationshipType, labels(m) AS ConnectedNodeLabels
                """

        if sets is None:
            with self.driver.session() as session:
                # remove duplicates (keep unique pairs of node labels and relationship types)
                result = session.run(query)
                result_set = {(tuple(record["NodeLabels"]),
                               record["RelationshipType"],
                               tuple(record["ConnectedNodeLabels"])) for record in result}

                # convert to dictionary
                relation_dict = {}
                for node_labels, relationship_type, connected_node_labels in result_set:
                    key = (node_labels[0], connected_node_labels[0])
                    relation_dict[key] = relationship_type
                # store in cache
                self.cache.set("label_and_relationship_type_sets", relation_dict, expire=self.expire)
                sets = relation_dict
                print(sets)
        return sets

    def get_all_nodes(self) -> list[Node]:
        """Get all nodes except 'Title' and 'Message'. Only return label and name."""
        nodes = self.cache.get("all_nodes")
        query = """
                MATCH (n)
                WHERE NOT 'Title' IN labels(n)
                    AND NOT 'Message' IN labels(n)
                RETURN labels(n) as label, n.name as name
                """
        if nodes is None:
            with self.driver.session() as session:
                result = session.run(query)
                nodes = [Node(label=record["label"][0], name=record["name"], properties={}) for record in result]
                self.cache.set("all_nodes", nodes, expire=self.expire)
        return nodes

    def get_all_relationships(self) -> list[Relationship]:
        """Get all relationships except 'Title' and 'Message'. Only return type, start_node, end_node."""
        relationships = self.cache.get("all_relationships")
        query = """
                MATCH (n)-[r]->(m)
                WHERE NOT 'Title' IN labels(n)
                    AND NOT 'Message' IN labels(n)
                    AND NOT 'Title' IN labels(m)
                    AND NOT 'Message' IN labels(m)
                RETURN type(r) AS type, n.name as start_node, m.name as end_node
                """
        if relationships is None:
            with self.driver.session() as session:
                result = session.run(query)
                relationships = [Relationship(type=record["type"], start_node=record["start_node"], end_node=record["end_node"],
                                              properties=None, start_node_label=None, end_node_label=None) for record in result]
                self.cache.set("all_relationships", relationships, expire=self.expire)
        return relationships
