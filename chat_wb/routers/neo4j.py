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


@neo4j_router.get("/message_nodes", tags=["label"])
def get_message_nodes_api():
    """すべてのtitle, messageのラベルと名前をリストとして取得する"""
    nodes = get_message_nodes()
    return nodes

@neo4j_router.get("/message_relationships", tags=["label"])
def get_message_relationships_api():
    """すべてのtitle,message起点のリレーションシップと名前をリストとして取得する"""
    relationships = get_message_relationships()
    return relationships
