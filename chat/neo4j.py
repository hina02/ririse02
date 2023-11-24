import logging
import os
import re
from typing import Any

from models.neo4j import Node, Relation
from neo4j import GraphDatabase

# ロガー設定
logger = logging.getLogger(__name__)


# ドライバの初期化
uri = os.environ["NEO4J_URI"]
username = "neo4j"
password = os.environ["NEO4J_PASSWORD"]
driver = GraphDatabase.driver(uri, auth=(username, password))


# ノードの更新
# ノードが存在しない場合、ノードを作成する
# ノードが存在する場合、ノードのプロパティを更新する
# 複数のラベルを指定する場合、label = "Vendor:Organization"。
def create_update_node(label: str, name: str, info: dict | None = None):
    # None、空のリスト、空の辞書を削除する（上書き防止のため）
    if info is not None:
        info = {k: v for k, v in info.items() if v is not None and v != [] and v != {}}

    with driver.session() as session:
        result = session.run(f"MATCH (n:{label} {{name: $name}}) RETURN n", name=name)
        # ノードが存在しない場合、作成する。
        if result.single() is None:
            properties = {"name": name}

            # 人名の場合は、姓名を分けて登録する。
            if label == "Person":
                from namedivider import BasicNameDivider

                divider = BasicNameDivider()
                divided_name = divider.divide_name(name).to_dict()
                name_variations = [
                    n
                    for n in [divided_name.get("family"), divided_name.get("given")]
                    if n is not None
                ]
                properties["name_variations"] = name_variations

            # info 辞書が渡された場合、その内容を properties に追加する
            if info:
                properties.update(info)

            # Cypherクエリを動的に作成する
            props_string = ", ".join([f"{k}: ${k}" for k in properties.keys()])
            session.run(f"CREATE (:{label} {{{props_string}}})", **properties)

            message = f"Node {{{label}:{name}}} created."
            logging.info(message)
            return {"status": "success", "message": message}

        # ノードが存在する場合、プロパティを更新する。
        else:
            if info:
                session.run(
                    f"MATCH (n:{label} {{name: $name}}) SET n += $props",
                    name=name,
                    props=info,
                )
                result = session.run(
                    f"MATCH (n:{label} {{name: $name}}) RETURN properties(n) as updated_properties",
                    name=name,
                )
                updated_properties = result.single().get("updated_properties")

                message = f"Node {{{label}:{name}}} already exists.\nProperty updated:{updated_properties}."
                logging.info(message)
                return {"status": "success", "message": message}
            else:
                message = f"Node {{{label}:{name}}} already exists."
                logging.info(message)
                return {"status": "success", "message": message}


# property要素について、上書きせずに、値を追加する関数。node_idを返す。
def create_update_append_node(
    label: str, name: str, property_name: str, property_value: str
):
    with driver.session() as session:
        result = session.run(f"MATCH (n:{label} {{name: $name}}) RETURN n", name=name)

        # ノードが存在しない場合、作成する。
        if result.single() is None:
            properties = {
                "name": name,
                property_name: [property_value],
            }  # プロパティをリストとして初期化

            # Cypherクエリを動的に作成する
            props_string = ", ".join([f"{k}: ${k}" for k in properties.keys()])
            session.run(
                f"CREATE (n:{label} {{{props_string}}}) RETURN id(n) as node_id",
                **properties,
            )
            result = session.run(
                f"MATCH (n:{label} {{name: $name}}) RETURN id(n) as node_id", name=name
            )
            node_id = result.single()["node_id"]

            message = f"Node {{{label}:{name}}} created."
            logging.info(message)
            return {"status": "success", "message": message, "node_id": node_id}

        # ノードが存在する場合、指定されたプロパティを更新する。
        else:
            update_query = f"""
            MATCH (n:{label} {{name: $name}})
            SET n.{property_name} = CASE 
                WHEN n.{property_name} IS NULL THEN [$property_value] 
                ELSE n.{property_name} + [$property_value] 
            END
            RETURN id(n) as node_id
            """
            result = session.run(update_query, name=name, property_value=property_value)
            node_id = result.single()["node_id"]

            message = f"Node {{{label}:{name}}} already exists.\nProperty updated."
            logging.info(message)
            return {"status": "success", "message": message, "node_id": node_id}


# optionのリレーションシップを作成する
def create_update_relationship(
    node1_id: int,
    node2_id: int,
    time: str | None,
    relation_type: str,
    content: str | None,
):
    # timeがNoneの時は、マジックワードを渡して管理する。
    if time is None:
        time = "base"

    with driver.session() as session:
        # 指定されたtime値でリレーションシップを検索
        existing_record = session.run(
            f"""
            MATCH (n1)-[r:{relation_type}]->(n2)
            WHERE r.time = $time AND id(n1) = $node1_id AND id(n2) = $node2_id
            RETURN r.content as content
        """,
            node1_id=node1_id,
            node2_id=node2_id,
            time=time,
        ).single()

        existing_contents = existing_record["content"] if existing_record else []

        existing_contents.append(content)
        # 重複を削除、Noneを削除
        contents = list(set(existing_contents))
        contents = list(filter(None, contents))

        # 既存のリレーションシップが存在する場合、内容を更新
        if existing_record:
            session.run(
                f"""
                MATCH (n1)-[r:{relation_type}]->(n2)
                WHERE r.time = $time AND id(n1) = $node1_id AND id(n2) = $node2_id
                SET r.time = $time, r.content = $contents
            """,
                node1_id=node1_id,
                node2_id=node2_id,
                time=time,
                contents=contents,
            )

            message = f"""Relationship {{Node1:{node1_id}}}-{{{relation_type}:{time}}}
                            ->{{Node2:{node2_id}}} already exists.\nProperty updated:{{'contents':{contents}}}"""
            logging.info(message)
            return {"status": "success", "message": message}

        # リレーションシップが存在しない場合、新しいリレーションシップを作成
        else:
            session.run(
                f"""
                MATCH (n1), (n2)
                WHERE id(n1) = $node1_id AND id(n2) = $node2_id
                CREATE (n1)-[:{relation_type} {{time: $time, content: $contents}}]->(n2)
            """,
                node1_id=node1_id,
                node2_id=node2_id,
                time=time,
                contents=contents,
            )

            message = f"""Relationship {{Node1:{node1_id}}}-{{{relation_type}:{time}}}
                            ->{{Node2:{node2_id}}} created.\nProperty:{{'contents':{contents}}}"""
            logging.info(message)
            return {"status": "success", "message": message}


# ノードを削除する
def delete_node(label: str = None, name: str = None, node_id: int = None):
    with driver.session() as session:
        # IDでノードを削除する
        if node_id:
            result = session.run(
                "MATCH (n) WHERE id(n) = $node_id DETACH DELETE n RETURN count(n) as deleted_count",
                node_id=node_id,
            )
            deleted_count = result.single().get("deleted_count")
            if deleted_count > 0:
                return logging.info(message=f"Node {{node_id:{node_id}}} deleted.")
            else:
                return logging.info(message=f"Node {{node_id:{node_id}}} not found.")
        # ラベルと名前でノードを削除する
        else:
            result = session.run(
                f"MATCH (n:{label} {{name: $name}}) DETACH DELETE n RETURN count(n) as deleted_count",
                name=name,
            )
            deleted_count = result.single().get("deleted_count")
            if deleted_count > 0:
                return logging.info(message=f"Node {{{label}:{name}}} deleted.")
            else:
                return logging.info(message=f"Node {{{label}:{name}}} not found.")


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
        return logging.info(message=f"Relationship_id {{{relationship_id}}} deleted.")
    else:
        return logging.info(message=f"Relationship_id {{{relationship_id}}} not found.")

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


# Use in Triplet
def remove_suffix(name: str) -> str:
    # 正規表現パターンで、接尾語を列挙し、それらを末尾から削除する
    jk_suffixes = [
        "りん",
        "ぴ",
        "っぴ",
        "ゆん",
        "ぽん",
        "むー",
        "みー",
        "先生",
        "せんせえ",
        "せんせい",
        "先輩",
        "せんぱい",
        "後輩",
    ]
    otaku_suffixes = [
        "たん",
        "たそ",
        "ほん",
        "しぃ",
        "ちゃま",
        "りり",
        "氏",
        "師匠",
        "師",
        "老師",
        "殿",
        "どの",
        "姫",
        "ひめ",
        "殿下",
        "陛下",
        "閣下",
        "太郎",
        "たろー",
        "きち",
    ]  # prefix "同志",
    role_suffixes = [
        "組長",
        "会長",
        "社長",
        "副社長",
        "部長",
        "課長",
        "係長",
        "監督",
        "選手",
        "将軍",
        "博士",
        "教授",
        "マネージャー",
        "スタッフ",
        "メンバー",
        "オーナー",
        "リーダー",
        "ディレクター",
        "オフィサー",
        "一等兵",
        "上等兵",
        "伍長",
        "軍曹",
        "曹長",
        "少尉",
        "中尉",
        "大尉",
        "少佐",
        "中佐",
        "大佐",
        "准将",
        "少将",
        "中将",
        "大将",
        "元帥",
        "大元帥",
        "海兵",
        "上級海兵",
        "提督",
    ]
    all_suffixes = (
        [
            "さん",
            "くん",
            "君",
            "ちゃん",
            "さま",
            "様",
        ]
        + jk_suffixes
        + otaku_suffixes
        + role_suffixes
    )
    pattern = r"(" + "|".join(all_suffixes) + ")$"
    return re.sub(pattern, "", name)


# 指定ノードの情報
# nameがnameに一致、或いはname_variationに含まれるノードのプロパティを取得する
# Personの場合は、name_variationsを併せて検索する。
def get_node(name: str, label: str | None = None) -> list[Node] | None:
    with driver.session() as session:
        if label is None:
            result = session.run(
                "MATCH (n) WHERE $name IN n.name_variations OR n.name = $name RETURN id(n) as node_id, properties(n) as properties",
                name=name,
            )
        elif label == "Person":  # Personの場合は、name_variationsを併せて検索する
            name = remove_suffix(name)  # 接尾語を削除する
            result = session.run(
                "MATCH (n:Person) WHERE $name IN n.name_variations OR n.name = $name RETURN id(n) as node_id, properties(n) as properties",
                name=name,
            )
        else:
            result = session.run(
                f"MATCH (n:{label} {{name: $name}}) RETURN id(n) as node_id, properties(n) as properties",
                name=name,
            )
        nodes = []
        for record in result:
            nodes.append({"id": record["node_id"], "properties": record["properties"]})
        return nodes if nodes else None


# ノードから特定のリレーションタイプを持つノードを取得する
def get_related_nodes_by_relation(
    label: str, name: str, relation_type: str
) -> list[Node] | None:
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (n:{label} {{name: $name}})-[r:{relation_type}]->(node)
            RETURN id(node) as node_id, node.name as node_name, labels(node) as node_labels, node as properties
        """,
            name=name,
        )
        nodes = []
        processed_node_ids = set()  # 処理済みのノードIDを保持するための集合
        for record in result:
            node_id = record["node_id"]
            if node_id not in processed_node_ids:  # このノードIDが処理済みかどうかをチェック
                node = Node(
                    id=record["node_id"],
                    name=record["node_name"],
                    label=record["node_labels"][0] if record["node_labels"] else None,
                    properties=dict(record["properties"]),
                )
                nodes.append(node)
                processed_node_ids.add(node_id)  # このノードIDを処理済みとして記録します
        return nodes


# ノードからすべてのリレーションとプロパティ（content）、終点ノードを得る
def get_all_relationships(label: str, name: str) -> list[Relation] | None:
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (a:{label} {{name: $name}})-[r]->(b)
            RETURN  id(r) as relationship_id, type(r) as relationship_type, r.content as content, r.time as time, id(b) as node2_id, b.name as name2
        """,
            name=name,
        )
        relationships = []
        for record in result:
            relation = Relation(
                id=record["relationship_id"],
                type=record["relationship_type"],
                content=record["content"],
                time=record.get("time", None),
                node1=name,
                node2=record["name2"],
            )
            relationships.append(relation)
        return relationships if relationships else None


# ノードとノードの間にあるすべてのリレーションとプロパティ（content）を得る
def get_all_relationships_between(
    label1: str, label2: str, name1: str, name2: str
) -> list[Relation] | None:
    with driver.session() as session:
        result = session.run(
            f"""
      MATCH (a:{label1} {{name: $name1}})-[r]->(b:{label2} {{name: $name2}})
      RETURN  id(r) as relationship_id, type(r) as relationship_type, r.content as content, r.time as time""",
            name1=name1,
            name2=name2,
        )
        relationships = []
        for record in result:
            relation = Relation(
                id=record["relationship_id"],
                type=record["relationship_type"],
                content=record["content"],
                time=record["time"],
                node1=name1,
                node2=name2,
            )
            relationships.append(relation)
        return relationships if relationships else None
