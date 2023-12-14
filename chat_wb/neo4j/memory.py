from neo4j import GraphDatabase
import os
import json
from datetime import datetime
from logging import getLogger
from functools import lru_cache
from typing import Literal
from chat_wb.models import WebSocketInputData, Triplets, Node
from openai_api.common import get_embedding

# ロガー設定
logger = getLogger(__name__)


# ドライバの初期化
uri = os.environ["NEO4J_URI"]
username = "neo4j"
password = os.environ["NEO4J_PASSWORD"]
driver = GraphDatabase.driver(uri, auth=(username, password))


def show_index() -> list[str]:
    """NEO4jのインデックスを確認して、インデックス名をリストで返す"""
    with driver.session() as session:
        results = session.run(
            """
        SHOW INDEXES YIELD name, type, labelsOrTypes, properties, options
        WHERE type = 'VECTOR'"""
        )
        response = []
        for result in results:
            response.append(result["name"])
        return response


@lru_cache
def check_index() -> list[str]:
    """NEO4jのインデックスを確認して、ない場合、インデックスを作成する。"""
    indices = show_index()
    if "Title" not in indices:
        with driver.session() as session:
            # ラベルの作成
            session.run("""CREATE (:Title)""")
            session.run("""CREATE (:Message)""")
            # インデックスの作成
            session.run(
                """CALL db.index.vector.createNodeIndex(
                    $label, $label, 'embedding', 1536, 'cosine')""",
                label="Title",
            )
            session.run(
                """CALL db.index.vector.createNodeIndex(
                    $label, $label, 'embedding', 1536, 'cosine')""",
                label="Message",
            )
        indices = show_index()
        logger.info(f"Vector Index created: {indices}")
    else:
        logger.info(f"Vector Index already exists: {indices}")

    return indices


NEO4J_INDEX = check_index()


def get_messages(title: str) -> list[dict]:
    """タイトルを指定して、メッセージを取得する"""
    with driver.session() as session:
        results = session.run(
            """
            MATCH (a:Title {title: $title})-[:CONTAIN]->(b:Message)
            RETURN ID(b) as node_id, b as properties""",
            title=title,
        )

        nodes = []
        for record in results:
            properties = dict(record["properties"])
            properties["id"] = record["node_id"]
            if "embedding" in properties:
                del properties["embedding"]
            nodes.append(properties)
        nodes = sorted(nodes, key=lambda x: x["create_time"])
    return nodes


def get_titles() -> list[str]:
    """タイトルのリストを取得する"""
    with driver.session() as session:
        results = session.run(
            """
            MATCH (a:Title)
            WHERE a.title IS NOT NULL
            RETURN a.title as title"""
        )

        nodes = []
        for record in results:
            nodes.append(record["title"])
    return nodes


def query_vector(query: str, label: Literal['Title', 'Message'], k: int = 3):
    """インデックスを作成したラベル(Title, Message)から、ベクトルを検索する"""
    vector = get_embedding(query)

    with driver.session() as session:
        results = session.run(
            """
            CALL db.index.vector.queryNodes($label, $k, $vector)
            YIELD node, score
            RETURN node AS properties, score""",
            label=label,
            k=k,
            vector=vector,
        )

        nodes = []
        for record in results:
            properties = dict(record["properties"])
            if "embedding" in properties:
                del properties["embedding"]

            score = record["score"]
            properties["score"] = score
            nodes.append(properties)

        nodes = sorted(nodes, key=lambda x: x["score"], reverse=True)

    return nodes


def query_vector_with_filter(query: str, entity: list[Node], k: int = 20):
    """entityとのマッチを用いて、messageのquery_vector結果をフィルタリングする。"""
    nodes = query_vector(query, "Message", k=k)

    # [nodes(node.user_input_entity.nodes)]に、[entityに含まれるnode.name]に合致するものがある場合、filtered_nodesに格納
    filtered_nodes = []
    entity_node_names = [node.name for node in entity]

    for node in nodes:
        # Message nodeから、作成時のuser_input_entityを取得
        user_input_entity_json = node.get("user_input_entity")
        if user_input_entity_json:
            user_input_entity = json.loads(user_input_entity_json)
            node_entities = user_input_entity.get("nodes", [])

        # 一つでもentityに含まれるnode.nameがあれば、filtered_nodesに追加
        for node_entity in node_entities:
            if node_entity.get("name") in entity_node_names:
                filtered_nodes.append(node)
                break
    return filtered_nodes


async def create_and_update_title(title: str, new_title: str | None = None) -> int:
    """Titleノードを作成、更新する"""
    # title名でベクトル作成
    pa_vector = get_embedding(new_title) if new_title else get_embedding(title)
    # 現在のUTC日時を取得し、ISO 8601形式の文字列に変換
    current_utc_datetime = datetime.utcnow()
    current_time = current_utc_datetime.isoformat() + "Z"

    with driver.session() as session:
        session.run(
            """
            MERGE (a:Title {title: $title})
            ON CREATE SET a.create_time = $create_time, a.update_time = $create_time, a.title = $new_title
            ON MATCH SET a.update_time = $update_time, a.title = $new_title
            WITH a
            CALL db.create.setNodeVectorProperty(a, 'embedding', $vector)
            """,
            title=title,
            new_title=new_title if new_title else title,
            create_time=current_time,
            update_time=current_time,
            vector=pa_vector,
        )
        logger.info(f"Title Node created: {title}")
        return True


async def store_message(
    input_data: WebSocketInputData,
    ai_response: str,
    user_input_entity: Triplets | None = None,
) -> int:
    source = input_data.source
    title = input_data.title
    user_input = input_data.input_text
    AI = input_data.AI
    former_node_id = input_data.former_node_id
    current_utc_datetime = datetime.utcnow()
    create_time = current_utc_datetime.isoformat() + "Z"
    update_time = create_time

    with driver.session() as session:
        # 親ノードを更新する(update_timeを更新する)
        title_id = session.run(
            """
                MERGE (a:Title {title: $title})
                ON CREATE SET a.create_time = $create_time, a.update_time = $create_time
                ON MATCH SET a.update_time = $update_time
                RETURN id(a) AS title_id
                """,
            title=title,
            create_time=create_time,
            update_time=update_time,
        ).single()["title_id"]

        # メッセージノードを作成
        vector = get_embedding(ai_response)  # どれを登録するべきか悩ましい
        result = session.run(
            """CREATE (b:Message {create_time: $create_time, source: $source,
                             user_input: $user_input, user_input_entity: $user_input_entity,
                             AI: $AI, ai_response: $ai_response})
                             WITH b
                             CALL db.create.setNodeVectorProperty(b, 'embedding', $vector)
                             RETURN id(b) AS node_id
                            """,
            create_time=create_time,
            source=source,
            user_input=user_input,
            user_input_entity=user_input_entity.model_dump_json() if user_input_entity else None,
            AI=AI,
            ai_response=ai_response,
            vector=vector,
        )
        new_node_id = result.single()["node_id"]
        logger.info(f"Message Node created: {new_node_id}")

        # 親ノード(Title)からのリレーション(CONTAIN)を作成する
        session.run(
            "MATCH (a), (b) WHERE id(a) = $title_id AND id(b) = $new_node_id CREATE (a)-[:CONTAIN]->(b)",
            title_id=title_id,
            new_node_id=new_node_id,
        )

        # 前のノード(Message)からのリレーション(FOLLOW)と(PRECEDES)を作成
        if former_node_id is not None:
            session.run(
                """MATCH (b), (c)
                        WHERE id(b) = $new_node_id AND id(c) = $former_node_id
                        CREATE (b)-[:FOLLOW]->(c)
                        CREATE (c)-[:PRECEDES]->(b)""",
                new_node_id=new_node_id,
                former_node_id=former_node_id,
            )
            logger.info(f"Message Node Relation created: {new_node_id}")

        # user_input_entityへのリレーションを作成
        # 情報をretrieveしやすいように、create_time, propertiesを保存する。
        if user_input_entity is not None:
            for node in user_input_entity.nodes:
                properties = node.properties if node.properties is not None else {}
                properties["created_time"] = create_time
                logger.info(f"properties: {properties}")
                session.run(
                    f"""
                        MATCH (b) WHERE id(b) = $new_node_id
                        MATCH (d:`{node.label}` {{name: $name}})
                        CREATE (b)-[r:CONTAIN]->(d)
                        SET r = $props
                    """,
                    name=node.name,
                    new_node_id=new_node_id,
                    props=properties
                )
                logger.info(f"Message Node Relation with Entity created: {node}")

    return new_node_id
