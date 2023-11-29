from neo4j import GraphDatabase
import os
import json
import time
from logging import getLogger
from functools import lru_cache
# from chat_wb.neo4j.triplet import run_sequences
from chat_wb.models.wb import WebSocketInputData
from openai_api.common import get_embedding
from chat_wb.models.neo4j import Triplets

# ロガー設定
logger = getLogger(__name__)


# Neo4jに保存
# ノードを作成する
# 親ノード(Title)からのリレーション(CONTAIN)を作成する
# 前のノード(Message)からのリレーション(FOLLOW)を作成する
# 前のノード(Message)へのリレーション(PRECEDES)を作成する

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


def query_vector(query: str, label: str, k: int = 3):
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


async def store_message(
    input_data: WebSocketInputData,
    ai_response: str,
    user_input_entity: Triplets | None = None,
) -> int:
    title = input_data.title
    user_input = input_data.input_text
    former_node_id = input_data.former_node_id
    create_time = time.time()
    update_time = create_time

    with driver.session() as session:
        # 親ノードTitleが無ければ、作成する
        pa_result = session.run(
            """
                                MERGE (a:Title {title: $title})
                                ON CREATE SET a.create_time = $create_time, a.update_time = $create_time
                                ON MATCH SET a.update_time = $update_time
                                RETURN CASE WHEN a.create_time = $create_time THEN 'NOT_FOUND' ELSE 'FOUND' END AS status
                                """,
            title=title,
            create_time=create_time,
            update_time=update_time,
        )

        # 親ノードTitleが新規作成の場合のベクトル作成
        if pa_result == "NOT_FOUND":
            pa_vector = get_embedding(title)
            session.run(
                """
                        MERGE (a:Title {title: $title})
                        db.create.setVectorProperty('Title', 1536, $vector))""",
                title=title,
                vector=pa_vector,
            )
            logger.info(f"Title Node created: {title}")

        # メッセージノードを作成
        vector = get_embedding(ai_response)  # どれを登録するべきか悩ましい
        result = session.run(
            """CREATE (b:Message {create_time: $create_time,
                             user_input: $user_input, user_input_entity: $user_input_entity,
                             ai_response: $ai_response})
                             WITH b
                             CALL db.create.setVectorProperty(b, 'embedding', $vector)
                             YIELD node
                             RETURN id(b) AS node_id""",
            create_time=create_time,
            user_input=user_input,
            user_input_entity=json.dumps(user_input_entity),
            ai_response=ai_response,
            vector=vector,
        )
        new_node_id = result.single()["node_id"]
        logger.info(f"Message Node created: {new_node_id}")

        # 親ノード(Title)からのリレーション(CONTAIN)を作成する　動いてない？？
        session.run(
            "MATCH (a:Title {title: $title}), (b:Message {user_input: $user_input}) CREATE (a)-[:CONTAIN]->(b)",
            title=title,
            user_input=user_input,
        )

        # 前のノード(Message)からのリレーション(FOLLOW)と(PRECEDES)を作成
        if former_node_id is not None:
            session.run(
                """MATCH (b:Message), (c:Message)
                        WHERE id(b) = $new_node_id AND id(c) = $former_node_id
                        CREATE (b)-[:FOLLOW]->(c)
                        CREATE (c)-[:PRECEDES]->(b)""",
                new_node_id=new_node_id,
                former_node_id=former_node_id,
            )
            logger.info(f"Message Node Relation created: {new_node_id}")
    return new_node_id


# chatGPTのjsonファイルから、Neo4jに保存するデータを抽出する 未アップデート
def data_from_chatGPT(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    organized_data = []

    for item in data:
        single_data = {}
        single_data["title"] = item.get("title", None)

        conversations = []
        conversation_set = {}
        for key, value in item.get("mapping", {}).items():
            message = value.get("message", {})
            author_role = None
            if message and message.get("author"):
                author_role = message.get("author").get("role", None)

            if author_role == "user":
                conversation_set["user_input"] = message.get("content", {}).get(
                    "parts", []
                )[0]
            elif author_role == "assistant":
                conversation_set["ai_response"] = message.get("content", {}).get(
                    "parts", []
                )[0]
                conversation_set["create_time"] = message.get("create_time", None)

            if "user_input" in conversation_set and "ai_response" in conversation_set:
                conversations.append(conversation_set.copy())
                conversation_set.clear()

        single_data["conversations"] = conversations
        organized_data.append(single_data)

    # 抽出したデータをJSON形式で保存
    with open("organized_data.json", "w") as f:
        json.dump(organized_data, f, ensure_ascii=False, indent=4)

    return organized_data


def store_data_from_chatGPT(file_path: str):
    organized_data = data_from_chatGPT(file_path)

    for item in organized_data:
        title = item["title"]

        former_node_id = None
        for conversation in item:
            user_input = conversation["user_input"]
            ai_response = conversation["ai_response"]
            create_time = conversation["create_time"]
            former_node_id = store_message(
                title, user_input, ai_response, former_node_id, create_time
            )
