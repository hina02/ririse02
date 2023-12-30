from neo4j import GraphDatabase
import os
from datetime import datetime
from logging import getLogger
from functools import lru_cache
from typing import Literal
from chat_wb.models import WebSocketInputData, Triplets, Node, Relationships
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
            if "create_time" in properties:
                properties["create_time"] = properties["create_time"].strftime("%Y-%m-%dT%H:%M:%SZ")
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
    """インデックスを作成したラベル(Title, Message)から、ベクトルを検索する。基本形。直接は使用していない。"""
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


from utils.common import atimer
@atimer
async def query_messages(query: str, k: int = 3, threshold: float = 0.9, time_threshold: int = 365) -> Triplets:
    """ベクトル検索でメッセージを取得し、深さ2までのノードを取得し、関連するEntityを取得する。
        Message → Entity → Entityなので、一方向のみの探索で良い。
        期せずして、Message → Message → Entity も取得している。"""
    vector = get_embedding(query)
    with driver.session() as session:
        results = session.run(
                """
                CALL db.index.vector.queryNodes('Message', $k, $vector)
                YIELD node, score
                WHERE score > $threshold AND node.create_time > datetime() - duration({days: $time_threshold})
                WITH node AS messageNode, score
                ORDER BY score DESC
                LIMIT $k

                MATCH path = (messageNode)-[r*1..2]->(end)
                UNWIND relationships(path) as rel

                WITH rel
                WHERE type(rel) <> 'CONTAIN'

                RETURN
                    type(rel) as relationship_type, properties(rel) as properties,
                    COALESCE(startNode(rel).name, startNode(rel).user_input) as start_node_name, labels(startNode(rel))[0] as start_node_label, properties(startNode(rel)) as start_node_properties,
                    COALESCE(endNode(rel).name, endNode(rel).user_input) as end_node_name, labels(endNode(rel))[0] as end_node_label, properties(endNode(rel)) as end_node_properties
                """,
                k=k,
                vector=vector,
                threshold=threshold,
                time_threshold=time_threshold,
            )

        nodes = set()
        relationships = set()
        for record in results:
            # Messageノードを除去
            if record["start_node_label"] == "Message" or record["end_node_label"] == "Message":
                continue
            # ノード、リレーションシップを作成
            start_node = Node(label=record["start_node_label"], name=record["start_node_name"], properties=record["start_node_properties"])
            end_node = Node(label=record["end_node_label"], name=record["end_node_name"], properties=record["end_node_properties"])
            nodes.add(start_node)
            nodes.add(end_node)
            relationships.add(Relationships(
                type=record["relationship_type"],
                properties=record["properties"],
                start_node=start_node.name,
                end_node=end_node.name,
                start_node_label=start_node.label,
                end_node_label=end_node.label,
            ))
        logger.info(f"nodes: {len(nodes)}, relationships: {len(relationships)}")

        triplets = Triplets(nodes=list(nodes), relationships=list(relationships))
        return triplets


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
