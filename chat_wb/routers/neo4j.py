from fastapi import APIRouter, Body
from logging import getLogger
import pandas as pd
from chat_wb.cache import (
    fetch_labels,
    fetch_node_names,
    fetch_relationships,
    fetch_label_and_relationship_type_sets,
)
from chat_wb.neo4j.neo4j import (
    get_node,
    get_node_relationships,
    get_all_nodes,
    get_all_relationships,
    integrate_nodes,
    delete_node,
    create_update_node
)

from chat_wb.models import Node

logger = getLogger(__name__)

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


# For Character Settings
# get node
@neo4j_router.get("/get_node/{label}/{name}", tags=["node"])
async def get_node_api(label: str, name: str):
    """ノードを取得する。"""
    result = await get_node(label=label, name=name)
    logger.info(f"result: {result}")
    return result[0] if result else None


# get node relationship
@neo4j_router.get("/get_node_relationships/{label}/{name}", tags=["node"])
async def get_node_relationship_api(label: str, name: str, depth: int = 1):
    """ノードのリレーションシップ（Messageを除く）を取得する。"""
    result = await get_node_relationships(label=label, name=name, depth=depth)
    return result if result else None


# integrate node
@neo4j_router.put("/integrate_nodes", tags=["node"])
async def integrate_nodes_api(node1: Node = Body(...), node2: Node = Body(...)):
    """ノード2からノード1へ、名前、プロパティ、リレーションシップを統合する。ノード2の削除は行わない。"""
    # node1, node2を確認する。
    _node1 = await get_node(node1.label, node1.name)
    _node2 = await get_node(node2.label, node2.name)
    if not _node1 or not _node2:
        if not _node1 and not _node2:
            return {"status": False, "message": f"Node {node1.name} and {node2.name} not found."}
        elif not _node1:
            return {"status": False, "message": f"Node {node1.name} not found."}
        elif not _node2:
            return {"status": False, "message": f"Node {node2.name} not found."}
    else:
        return await integrate_nodes(node1, node2)


@neo4j_router.delete("/delete_node/{label}/{name}", tags=["node"])
async def delete_node_api(label: str, name: str):
    """ノードを削除する。"""
    return delete_node(label=label, name=name)


# create node
@neo4j_router.post("/create_update_node", tags=["node"])
async def create_update_node_api(node: Node = Body(...)):
    """ノードを新規作成、更新する。現在の想定は、character setting用途。"""
    label = node.label
    name = node.name
    if not label or not name:
        return {"status": False, "message": f"Label and Name should not empty. label: {label}, name: {name}"}
    properties = node.properties
    logger.info(f"node: {node}")

    if all(not isinstance(v, list) for v in properties.values()):
        # propertiesにリスト要素がない場合
        create_update_node(Node(label=label, name=name, properties=properties))
    else:
        # propertiesのリスト要素を展開する
        df = pd.DataFrame({k: pd.Series(v) if isinstance(v, list) else v for k, v in properties.items()})
        df = df.where(pd.notnull(df), None)                     # NaNをNoneに置き換える
        expanded_properties = df.to_dict(orient='records')      # DataFrameの各行を辞書に変換してリストにまとめる
        # ノードを作成、更新する
        for prop in expanded_properties:
            create_update_node(Node(label=label, name=name, properties=prop))

    result = await get_node(label=label, name=name)
    return result[0] if result else None
