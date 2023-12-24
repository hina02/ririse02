from neo4j import GraphDatabase
import os
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


def get_latest_messages(title: str, n: int = 7) -> list[dict] | None:
    """最新のメッセージを取得する"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (t:Title {title: $title})-[:CONTAIN]->(m:Message)
            RETURN m
            ORDER BY m.create_time DESC
            LIMIT $n
            """,
            title=title,
            n=n
        )
        messages = [record["m"] for record in result]
        return messages


def query_vector(query: str, label: Literal['Title', 'Message'], k: int = 3, threshold: float = 0.9, time_threshold: int = 365) -> list[dict]:
    """インデックスを作成したラベル(Title, Message)から、ベクトルを検索する"""
    vector = get_embedding(query)

    with driver.session() as session:
        results = session.run(
            """
            CALL db.index.vector.queryNodes($label, $k, $vector)
            YIELD node, score
            WHERE score > $threshold AND node.create_time > datetime() - duration({days: $time_threshold})
            RETURN node AS properties, score
            ORDER BY score DESC""",
            label=label,
            k=k,
            vector=vector,
            threshold=threshold,
            time_threshold=time_threshold,
        )

        nodes = []
        for record in results:
            properties = dict(record["properties"])
            # ベクトルデータを削除
            if "embedding" in properties:
                del properties["embedding"]
            # create_time, scoreの値を簡略化
            if "create_time" in properties:
                properties["create_time"] = properties["create_time"].strftime("%Y-%m-%dT%H:%M:%SZ")
            score = round(record["score"], 3)
            properties["score"] = score
            nodes.append(properties)

    return nodes


async def query_messages(user_input: str, k: int = 3):
    """user_inputを入れて、(user_input => user_input, ai_responseのセットを想定)
        （chat historyはノイズになるので追加しない）
        近しい過去のmessageのuser_input_entityを取り出す。
        取り出したentityは、関連するnode、relationshipsを得るため、get_memory_from_tripletに渡す。"""
    # vector search messages
    messages = query_vector(user_input, label="Message", k=k)   # [TODO] 前後のMessageの取得も検討

    # user_input_entityを取り出してtripletsにまとめる。
    nodes_set = set()
    relationships_set = set()

    for message in messages:
        user_input_entity = Triplets.model_validate_json(message.get("user_input_entity")) if message.get("user_input_entity") else None
        if user_input_entity is not None:
            nodes_set.update(user_input_entity.nodes)
            relationships_set.update(user_input_entity.relationships)
    user_input_entities = Triplets(nodes=list(nodes_set), relationships=list(relationships_set))

    # convert messages to [Node]
    message_nodes = []
    for message in messages:
        message.pop("user_input_entity", None)
        name = str(message.pop("create_time", "unknown date"))   # LLMが時系列を把握しやすいように、日時情報をnameに割り当て。
        message_nodes.append(Node(label="Message", name=name, properties=message))

    return message_nodes, user_input_entities


async def create_and_update_title(title: str, new_title: str | None = None):
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
            ON CREATE SET a.create_time = datetime($create_time), a.update_time = datetime($create_time), a.title = $new_title
            ON MATCH SET a.update_time = datetime($update_time), a.title = $new_title
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


# [OPTIMIZE] user_input_entityにrelationship情報を保存するのは冗長かもしれない。
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
    create_time = current_utc_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
    update_time = create_time

    with driver.session() as session:
        # 親ノードを更新する(update_timeを更新する)
        title_id = session.run(
            """
            MERGE (a:Title {title: $title})
            ON CREATE SET a.create_time = datetime($create_time), a.update_time = datetime($create_time)
            ON MATCH SET a.update_time = datetime($update_time)
            RETURN id(a) AS title_id
            """,
            title=title,
            create_time=create_time,
            update_time=update_time,
        ).single()["title_id"]

        # メッセージノードを作成
        embed_message = f"{source}: {user_input}\n {AI}: {ai_response}"
        vector = get_embedding(embed_message)  # user_input, ai_responseのセットを保存し、user_inputでqueryする想定
        result = session.run(
            """
            CREATE (b:Message {
                create_time: datetime($create_time),
                source: $source,
                user_input: $user_input,
                user_input_entity: $user_input_entity,
                AI: $AI,
                ai_response: $ai_response
            })
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
            logger.info(f"Message Node Relation created. id: {new_node_id}")

        # user_input_entityへのリレーションを作成
        # 情報をretrieveしやすいように、create_time, propertiesを保存する。
        if user_input_entity is not None:
            for node in user_input_entity.nodes:
                properties = node.properties if node.properties is not None else {}
                properties["create_time"] = create_time
                session.run(
                    f"""
                        MATCH (b) WHERE id(b) = $new_node_id
                        MATCH (d:`{node.label}` {{name: $name}})
                        CREATE (b)-[r:CONTAIN]->(d)
                        SET r = $props
                        SET r.create_time = datetime($create_time)
                    """,
                    name=node.name,
                    new_node_id=new_node_id,
                    props=properties,
                    create_time=create_time,
                )

    return new_node_id
