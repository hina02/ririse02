import time
from logging import getLogger
from typing import Union

import neo4j
from openai import OpenAI
from pydantic import ValidationError

from ..models import DocumentNode, MessageNode, Node, Relationship, SceneNode, TopicNode

# ロガー設定
logger = getLogger(__name__)


# Neo4j型の変換
def convert_neo4j_node_to_model(node: neo4j.graph.Node) -> Node | None:
    # Scene, MessageをNode型に変換する場合、propertiesを除去する。
    properties = dict(node)
    label = next(iter(node.labels), None)
    if label == "Scene":
        name = properties.get("scene")
        properties = {}
    elif label == "Message":
        name = properties.get("user_input")
        properties = {}
    else:
        name = properties.pop("name")
    try:
        return Node(
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
        or relationship.start_node.get("scene")
    )
    end_node_name = (
        relationship.end_node.get("name")
        or relationship.end_node.get("user_input")
        or relationship.end_node.get("scene")
    )
    if start_node_name and end_node_name:
        properties = dict(relationship)
        return Relationship(
            type=relationship.type,
            start_node=start_node_name,
            end_node=end_node_name,
            properties=properties,
            start_node_label=next(iter(relationship.start_node.labels), None),
            end_node_label=next(iter(relationship.end_node.labels), None),
        )


def convert_neo4j_system_node_to_model(
    label: str,
    node: dict,
) -> Union[SceneNode, TopicNode, MessageNode, DocumentNode, None]:
    properties = dict(node)

    # timestampは必ず存在する
    timestamp = properties.pop("timestamp").to_native()
    # end_timeが存在する場合は変換、そうでなければNoneを使用
    end_time = properties.pop("end_time").to_native() if "end_time" in properties else None

    try:
        match label:
            case "Scene":
                return SceneNode(timestamp=timestamp, end_time=end_time, **properties)
            case "Topic":
                return TopicNode(timestamp=timestamp, **properties)
            case "Message":
                return MessageNode(timestamp=timestamp, **properties)
            case "Document":
                return DocumentNode(timestamp=timestamp, **properties)
            case _:
                return None
    except (KeyError, ValidationError) as e:
        logger.error(e)
        return None


def normalize_key(key: str) -> str:
    """Normalize key for Neo4j. (label, type, property name, index)"""
    # 特殊記号（英数字、アンダースコア、スペース、ハイフン以外）を除去
    cleaned_key = "".join(char for char in key if char.isalnum() or char in [" ", "-"])
    # スペースとハイフンをアンダースコアに置換
    normalized_key = cleaned_key.replace(" ", "_").replace("-", "_")
    # 頭の数字を除去
    normalized_key = normalized_key.lstrip("0123456789")
    return normalized_key


# Embedding
client = OpenAI()


def get_embedding(text: str, model: str = "text-embedding-ada-002") -> list[float]:
    text = text.replace("\n", " ")
    result = client.embeddings.create(input=[text], model=model).data[0].embedding
    return result


def atimer(func):
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        logger.info(f"{func.__name__} Time: {round(end_time - start_time, 5)} seconds")
        return result

    return wrapper
