from logging import getLogger
import os
from typing import Any
from chat_wb.models import Node, Relationships, Triplets
from neo4j import GraphDatabase

# ロガー設定
logger = getLogger(__name__)

# ドライバの初期化
uri = os.environ["NEO4J_URI"]
username = "neo4j"
password = os.environ["NEO4J_PASSWORD"]
driver = GraphDatabase.driver(uri, auth=(username, password))


# ノードの更新
# property要素について、上書きせずに、値を追加する関数。node_idを返す。
def create_update_node(node: Node):
    label = node.label
    name = node.name
    properties = node.properties

    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (n:{label})
            WHERE n.name = $name OR $name IN n.name_variation
            RETURN id(n) as node_id
            """,
            name=name,
        ).single()
        node_id = result.get("node_id") if result else None

        # 既存のノードが存在し、新規プロパティがある場合、プロパティを更新する。（キーが重複する場合は追加）
        # プロパティはstrまたはlistのみをサポートする。（フロントから、JSONを介すため、文字列として要素が送られるため）
        if node_id:
            if properties:
                logger.info(f"properties: {properties}")
                set_clause = ", ".join([
                    f"n.{property_name} = CASE WHEN n.{property_name} IS NULL THEN ['{property_value}'] ELSE apoc.coll.toSet(n.{property_name} + ['{property_value}']) END"
                    for property_name, property_value in properties.items()
                ])
                update_query = f"""
                MATCH (n)
                WHERE id(n) = $node_id
                SET {set_clause}
                """
                session.run(update_query, node_id=node_id)
                # idが複数の場合、このクエリは実行されず、スルーされる。

                message = f"Node {{{label}:{name}}} already exists.\nProperty updated."
                logger.info(message)
                return {"status": "success", "message": message, "node_id": node_id}

        # ノードが存在しない場合、新しいノードを作成。
        else:
            # プロパティにnameを追加し、リストとして初期化
            properties = properties or {}
            properties["name"] = name
            merge_query = f"""
            MERGE (n:{label} {{name: $name}})
            ON CREATE SET {', '.join([f'n.{k} = ${k}' for k in properties.keys()])}
            RETURN id(n) as node_id
            """
            result = session.run(merge_query, **properties)
            node_id = result.single()["node_id"]

            message = f"Node {{{label}:{name}}} created."
            logger.info(message)
            return {"status": "success", "message": message, "node_id": node_id}


# optionのリレーションシップを作成する
def create_update_relationship(relationships: Relationships):
    start_node = relationships.start_node
    end_node = relationships.end_node
    relation_type = relationships.type
    properties = relationships.properties

    # ノードラベルがNoneの場合にクエリから省略する
    start_node_label = f":{relationships.start_node_label}" if relationships.start_node_label is not None else ""
    end_node_label = f":{relationships.end_node_label}" if relationships.end_node_label is not None else ""

    with driver.session() as session:
        # name_variationを考慮して、ノードを検索した後に、リレーションシップを検索する。
        result = session.run(
            f"""
            MATCH (n1{start_node_label}), (n2{end_node_label})
            WHERE (n1.name = $start_node OR $start_node IN n1.name_variation)
            AND (n2.name = $end_node OR $end_node IN n2.name_variation)
            MATCH (n1)-[r:{relation_type}]->(n2)
            RETURN id(r) as relationship_id
            """,
            start_node=start_node,
            end_node=end_node,
        ).single()
        relationship_id = result.get("relationship_id") if result else None

        # 既存のリレーションシップが存在し、新規プロパティがある場合、内容を更新
        if relationship_id:
            if properties:
                session.run(
                    """
                    MATCH ()-[r]->()
                    WHERE id(r) = $relationship_id
                    SET r += $properties
                    """,
                    properties=properties,
                    relationship_id=relationship_id,
                )  # idが複数の場合、このクエリは実行されず、スルーされる。

                message = f"""Relationship {{Node1:{start_node}}}-{{{relation_type}}}
                                ->{{Node2:{end_node}}} already exists.\nProperty updated:{{'properties':{properties}}}"""
                logger.info(message)
                return {"status": "success", "message": message}

        # リレーションシップが存在しない場合、新しいリレーションシップを作成
        else:
            properties = properties or {}
            session.run(
                f"""
                MATCH (n1{start_node_label} {{name: $start_node}}), (n2{end_node_label} {{name: $end_node}})
                MERGE (n1)-[r:{relation_type}]->(n2)
                ON CREATE SET r += $properties
                """,
                start_node=start_node,
                end_node=end_node,
                properties=properties,
            )


# ノードを削除する
def delete_node(label: str = None, name: str = None):
    with driver.session() as session:
        # ラベルと名前でノードを削除する
        result = session.run(
            f"MATCH (n:{label} {{name: $name}}) DETACH DELETE n RETURN count(n) as deleted_count",
            name=name,
        )
        deleted_count = result.single().get("deleted_count")
    if deleted_count > 0:
        message = f"Node {{{label}:{name}}} deleted."
        logger.info(message)
        return {"status": True, "message": message}
    else:
        message = f"Node {{{label}:{name}}} not found."
        logger.info(message)
        return {"status": False, "message": message}


# IDをもとにリレーションシップを削除する
def delete_relationship(relationship_id: int):
    with driver.session() as session:
        result = session.run(
            """
            MATCH ()-[r]->() WHERE id(r) = $relationship_id
            DELETE r
            RETURN count(r) as deleted_count
        """,
            relationship_id=relationship_id,
        )

        deleted_count = result.single().get("deleted_count")

    if deleted_count > 0:
        return logger.info(message=f"Relationship_id {{{relationship_id}}} deleted.")
    else:
        return logger.info(message=f"Relationship_id {{{relationship_id}}} not found.")


# 指定した範囲のノードのプロパティを取得する
def get_node_properties(
    label: str, skip: int, limit: int, order_by: str, ascend: bool = True
) -> list[dict[str, Any]] | None:
    properties = []

    # 昇順または降順を設定
    order_direction = "ASC" if ascend else "DESC"

    with driver.session() as session:
        # ORDER BY句を使用して指定した属性で並べ替えるクエリ
        query = f"MATCH (n:{label}) RETURN properties(n) as properties ORDER BY n.{order_by} {order_direction} SKIP {skip} LIMIT {limit}"
        result = session.run(query)
        for record in result:
            properties.append(record["properties"])

    return properties if properties else None


# ----------------------------------------------------------------

# # Use in Cache
# Neo4jのノードラベルをすべて取ってくる関数
def get_node_labels() -> list[str]:
    labels = []

    with driver.session() as session:
        result = session.run("CALL db.labels()")
        for record in result:
            labels.append(record["label"])

    return labels


# Neo4jのリレーションタイプをすべて取ってくる関数
def get_relationship_types() -> list[str]:
    relationship_types = []

    with driver.session() as session:
        result = session.run("CALL db.relationshipTypes()")
        for record in result:
            relationship_types.append(record["relationshipType"])

    return relationship_types


# ノードラベルとリレーションタイプのセットを取得する関数
def get_label_and_relationship_type_sets() -> dict | None:
    result_set = set()

    with driver.session() as session:
        result = session.run(
            """
            MATCH (n)-[r]->(m)
            RETURN labels(n) AS NodeLabels, type(r) AS RelationshipType, labels(m) AS ConnectedNodeLabels
        """
        )
        for record in result:
            node_labels = tuple(record["NodeLabels"])
            relationship_type = record["RelationshipType"]
            connected_node_labels = tuple(record["ConnectedNodeLabels"])

            # タプルをセットに追加
            result_set.add((node_labels, relationship_type, connected_node_labels))

    if result_set is None:
        return None
    # dictに変換
    relation_dict = {}
    for result in result_set:  # resultsはあなたのクエリの出力リストを指します。
        node_label1, relationship_type, node_label2 = (
            result[0][0],
            result[1],
            result[2][0],
        )
        key = (node_label1, node_label2)  # タプルをキーとして使用

        # 辞書にリレーションタイプを追加、既に存在する場合はスキップ
        if key not in relation_dict:
            relation_dict[key] = relationship_type

    return relation_dict


# ノードリスト
# 特定のラベルのノードの名前をリストとして取得する
def get_node_names(label: str) -> list[str]:
    names = []

    with driver.session() as session:
        result = session.run(f"MATCH (n:{label}) RETURN n.name as name")
        for record in result:
            names.append(record["name"])

    return names


# Title、Messageを除くすべてのノードのラベルと名前を取得する
def get_all_nodes() -> list[Node]:
    nodes = []

    with driver.session() as session:
        result = session.run("MATCH (n) WHERE NOT 'Title' IN labels(n) AND NOT 'Message' IN labels(n) RETURN labels(n) as label, n.name as name")
        for record in result:
            node = Node(label=record["label"][0], name=record["name"], properties=None)
            nodes.append(node)
    return nodes


# Title、Messageを除くすべてのリレーションシップのタイプと、始点ノード・終点ノードの名前を取得する
def get_all_relationships() -> list[str]:
    relationships = []

    with driver.session() as session:
        result = session.run(
            """
            MATCH (n)-[r]->(m)
            WHERE NOT 'Title' IN labels(n) AND NOT 'Message' IN labels(n) AND NOT 'Title' IN labels(m) AND NOT 'Message' IN labels(m)
            RETURN type(r) AS type, n.name as start_node, m.name as end_node
            """
        )
        for record in result:
            relationship = Relationships(type=record["type"], start_node=record["start_node"], end_node=record["end_node"], properties=None, start_node_label=None, end_node_label=None)
            relationships.append(relationship)

    return relationships


# 指定ノードの情報
# nameがnameに一致、或いはname_variationに含まれるノードのプロパティを取得する
# Personの場合は、name_variationsを併せて検索する。
async def get_node(label: str | None, name: str) -> list[Node] | None:
    label_clause = f":{label}" if label else ""
    with driver.session() as session:
        result = session.run(
            f"MATCH (n{label_clause}) WHERE $name IN n.name_variations OR n.name = $name RETURN labels(n)[0] as label, properties(n) as properties",
            name=name,
        )
        nodes = []
        for record in result:
            label = record["label"]
            properties = record["properties"]
            properties.pop("name", None)  # 'name'をpropertiesから除去
            node = Node(label=label, name=name, properties=record["properties"])
            nodes.append(node)
        logger.debug(f"nodes: {nodes}")
        return nodes if nodes else None

from utils.common import atimer
# ノードが増えてレスポンスが遅くなるようなら、一つのnameを受け取るクエリの非同期処理を検討する。
@atimer
async def get_node_relationships(names: list[str], depth: int = 1) -> Triplets | None:
    """指定した深さまでの双方向リレーションシップを取得する（Message,Titleを除く）。複数nameを受け取る。"""
    with driver.session() as session:
        results = session.run(
            f"""
            MATCH (start)
            WHERE start.name IN $names OR ANY(name_variation IN start.name_variation WHERE name_variation IN $names)
            MATCH path = (start)-[r*1..{depth}]-(end)
            WHERE NONE(node IN nodes(path) WHERE 'Message' IN labels(node) OR 'Title' IN labels(node))
            UNWIND r as rel
            RETURN type(rel) as relationship_type, properties(rel) as properties,
                startNode(rel).name as start_node_name, labels(startNode(rel))[0] as start_node_label, properties(startNode(rel)) as start_node_properties,
                endNode(rel).name as end_node_name, labels(endNode(rel))[0] as end_node_label, properties(endNode(rel)) as end_node_properties
            """,
            names=names,
            depth=depth,
        )
        nodes = set()
        relationships = []
        for record in results:
            start_node = Node(label=record["start_node_label"], name=record["start_node_name"], properties=record["start_node_properties"])
            end_node = Node(label=record["end_node_label"], name=record["end_node_name"], properties=record["end_node_properties"])
            nodes.add(start_node)
            nodes.add(end_node)
            relationships.append(Relationships(
                type=record["relationship_type"],
                properties=record["properties"],
                start_node=record["start_node_name"],
                end_node=record["end_node_name"],
                start_node_label=record["start_node_label"],
                end_node_label=record["end_node_label"],
            ))
        if nodes and relationships:
            triplets = Triplets(nodes=list(nodes), relationships=relationships)
        else:
            triplets = None
        logger.debug(f"triplets: {triplets}")

    return triplets


# ノードとノードの間にあるすべての双方向のリレーションとプロパティ（content）を得る。
async def get_node_relationships_between(
    label1: str, label2: str, name1: str, name2: str
) -> list[Relationships] | None:
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (a:{label1})-[r]-(b:{label2})
            WHERE $name1 IN a.name_variations OR a.name = $name1
                AND $name2 IN b.name_variations OR b.name = $name2
            RETURN  type(r) as relationship_type,
                startNode(r).name as start_node_name,
                endNode(r).name as end_node_name,
                r.properties as properties""",
            name1=name1,
            name2=name2,
        )
        relationships = []
        for record in result:
            relation = Relationships(
                type=record["relationship_type"],
                start_node=record["start_node_name"],
                end_node=record["end_node_name"],
                properties=record["properties"],
                start_node_label=label1,
                end_node_label=label2,
            )
            relationships.append(relation)
        logger.debug(f"relationships: {relationships}")
        return relationships if relationships else None


# ----------------------------------------------------------------
# Name variation Integration
async def integrate_nodes(node1: Node, node2: Node):
    """ノード2つを選択して、名前、プロパティ、リレーションシップを統合する。確実に確認してから削除すべきなので、削除は別に行う。"""
    message = f"Node {{{node1.label}:{node1.name}}} and {{{node2.label}:{node2.name}}} integrated."
    logger.info(message)
    integrate_node_names(node1, node2)
    integrate_node_properties(node1, node2)
    integrate_relationships(node1, node2)
    return {"status": True, "message": message}


# Use neo4j apoc plugin (neo4j aura db pre-installed)
def integrate_node_names(node1: Node, node2: Node):
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (n1:{node1.label} {{name: $name1}}), (n2:{node2.label} {{name: $name2}})
            SET n1.name_variation = CASE
                WHEN n1.name_variation IS NULL THEN [n1.name, n2.name]
                ELSE apoc.coll.toSet(n1.name_variation + [n1.name, n2.name])
            END
            RETURN properties(n1)
            """,
            name1=node1.name,
            name2=node2.name,
        )
        logger.info(result.single()[0])


def integrate_node_properties(node1: Node, node2: Node):
    with driver.session() as session:
        # n1のプロパティを取得
        result1 = session.run(
            f"MATCH (n1:{node1.label} {{name: $name1}}) RETURN properties(n1) AS props1",
            name1=node1.name,
        )
        props1 = result1.single()["props1"]

        # n2のプロパティを取得
        result2 = session.run(
            f"MATCH (n2:{node2.label} {{name: $name2}}) RETURN properties(n2) AS props2",
            name2=node2.name,
        )
        props2 = result2.single()["props2"]

        # 同じキーの値をリストに統合し、重複を避ける
        for key in set(props1.keys()).intersection(props2.keys()):
            if key != "name":  # 'name'プロパティをスキップ
                # props1[key]とprops2[key]がリストでない場合、それらを一要素のリストに変換
                props1_values = props1[key] if isinstance(props1[key], list) else [props1[key]]
                props2_values = props2[key] if isinstance(props2[key], list) else [props2[key]]
                props1[key] = list(set(props1_values + props2_values))

        # 統合したプロパティをn1にセット
        result = session.run(
            f"MATCH (n1:{node1.label} {{name: $name1}}) SET n1 = $props RETURN properties(n1)",
            name1=node1.name,
            props=props1,
        )
        logger.info(result.single()[0])


def integrate_relationships(node1: Node, node2: Node):
    with driver.session() as session:
        # node2開始点のリレーションシップをnode1に移す
        session.run(
            f"""
            MATCH (n2:{node2.label} {{name: $name2}})-[r]->(m)
            MATCH (n1:{node1.label} {{name: $name1}})
            CALL apoc.refactor.from(r, n1)
            YIELD input, output
            RETURN input, output;
            """,
            name1=node1.name,
            name2=node2.name,
        )
        # node2終点のリレーションシップをnode1に移す
        session.run(
            f"""
            MATCH (n2:{node2.label} {{name: $name2}})<-[r]-(m)
            MATCH (n1:{node1.label} {{name: $name1}})
            CALL apoc.refactor.to(r, n1)
            YIELD input, output
            RETURN input, output;
            """,
            name1=node1.name,
            name2=node2.name,
        )
