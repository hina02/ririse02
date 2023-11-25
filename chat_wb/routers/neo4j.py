from fastapi import APIRouter
from chat_wb.cache import (
    fetch_labels,
    fetch_node_names,
    fetch_relationships,
    fetch_label_and_relationship_type_sets,
)


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
