from fastapi import APIRouter
from chat_wb.cache import (
    fetch_labels,
    fetch_node_names,
    fetch_relationships,
    fetch_label_and_relationship_type_sets,
)
from chat_wb.neo4j.neo4j import get_all_nodes, get_all_relationships, get_message_nodes, get_message_relationships

neo4j_router = APIRouter()


# GET Label and Relationship　キャッシュから取得する
@neo4j_router.get("/node_labels", tags=["label"])
def get_node_labels_api():
    labels = fetch_labels()
    return labels


@neo4j_router.get("/relationship_types", tags=["label"])
def get_relationship_types_api():
    relationship_types = fetch_relationships()
    return relationship_types


@neo4j_router.get("/label_and_relationship_type_sets", tags=["label"])
def get_label_and_relationship_type_sets_api():
    label_and_relationship_type_sets = fetch_label_and_relationship_type_sets()
    return label_and_relationship_type_sets


@neo4j_router.get("/node_names/{label}", tags=["label"])
def get_node_names_api(label: str):
    """すべてのノードの名前をリストとして取得する"""
    nodes = fetch_node_names(label=label)
    return nodes

@neo4j_router.get("/all_nodes", tags=["label"])
def get_all_node_names_api():
    """すべてのノードのラベルと名前をリストとして取得する"""
    nodes = get_all_nodes()
    return nodes

@neo4j_router.get("/all_relationships", tags=["label"])
def get_all_relationships_api():
    """すべてのノードのラベルと名前をリストとして取得する"""
    relationships = get_all_relationships()
    return relationships

from logging import getLogger
logger = getLogger(__name__)

@neo4j_router.get("/message_nodes/{title}", tags=["label"])
def get_message_nodes_api(title: str):
    """すべてのtitle, messageのラベルと名前をリストとして取得する"""
    nodes = get_message_nodes(title)
    return nodes

@neo4j_router.get("/message_relationships/{title}", tags=["label"])
def get_message_relationships_api(title: str):
    """すべてのtitle,message起点のリレーションシップと名前をリストとして取得する"""
    relationships = get_message_relationships(title)
    return relationships

from chat_wb.neo4j.neo4j import integrate_nodes
from chat_wb.models.neo4j import Node, Relationships
@neo4j_router.get("/integrate_nodes", tags=["label"])
def integrate_nodes_api(label1:str, name1:str, label2:str, name2:str):
    """すべてのノードのラベルと名前をリストとして取得する"""
    node1 = Node.create(label=label1, name=name1, properties=None)
    node2 = Node.create(label=label2, name=name2, properties=None)
    integrate_nodes(node1, node2)