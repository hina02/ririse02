import re
from logging import getLogger
import neo4j
from pydantic import ValidationError
from ..models import Node, Relationship, Triplets, MessageNode


# ロガー設定
logger = getLogger(__name__)


# Neo4j型の変換
def convert_neo4j_node_to_model(node: neo4j.graph.Node) -> Node | None:
    # Title, MessageをNode型に変換する場合、propertiesを除去する。
    properties = dict(node)
    label = next(iter(node.labels), None)
    if label == "Title":
        name = properties.get("title")
        properties = None
    elif label == "Message":
        name = properties.get("user_input")
        properties = None
    else:
        name = properties.pop("name")

    try:
        return Node(
            id=node.id,
            label=label,
            name=name,
            properties=properties,
        )
    except KeyError as e:
        logger.error(e)
        return None


def convert_neo4j_relationship_to_model(relationship: neo4j.graph.Relationship) -> Relationship | None:
    start_node_name = (
        relationship.start_node.get("name")
        or relationship.start_node.get("user_input")
        or relationship.start_node.get("title")
    )
    end_node_name = (
        relationship.end_node.get("name")
        or relationship.end_node.get("user_input")
        or relationship.end_node.get("title")
    )
    if start_node_name and end_node_name:
        properties = dict(relationship)
        return Relationship(
            id=relationship.id,
            type=relationship.type,
            start_node=start_node_name,
            end_node=end_node_name,
            properties=properties if properties else None,
            start_node_label=next(iter(relationship.start_node.labels), None),
            end_node_label=next(iter(relationship.end_node.labels), None),
        )


def convert_neo4j_message_to_model(node: neo4j.graph.Node) -> MessageNode | None:
    properties = dict(node)
    try:
        user_input_entity = properties.get("user_input_entity", None)
        return MessageNode(
            id=node.id,
            source=properties["source"],
            user_input=properties["user_input"],
            AI=properties["AI"],
            ai_response=properties["ai_response"],
            user_input_entity=Triplets.model_validate_json(user_input_entity) if user_input_entity else None,
            create_time=properties["create_time"].to_native(),
        )
    except (KeyError, ValidationError) as e:
        logger.error(e)
        return None
