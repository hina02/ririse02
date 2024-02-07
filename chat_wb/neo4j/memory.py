from neo4j import GraphDatabase
import os
from datetime import datetime
from logging import getLogger
from functools import lru_cache
from chat_wb.models import WebSocketInputData, Triplets, TempMemory, MessageNode, NodeHistory
from chat_wb.neo4j.utils import convert_neo4j_node_to_model, convert_neo4j_relationship_to_model, convert_neo4j_message_to_model
from openai_api.common import get_embedding

# ロガー設定
logger = getLogger(__name__)


# ドライバの初期化
uri = os.environ["NEO4J_URI"]
username = "neo4j"
password = os.environ["NEO4J_PASSWORD"]
driver = GraphDatabase.driver(uri, auth=(username, password))


# Vector Index
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


# Get Titles, Messages
def get_messages(title: str, n: int) -> list[MessageNode]:
    """タイトルを指定して、最新のn個のメッセージを取得する"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (n:Title {title: $title})-[:CONTAIN]->(m:Message)
            WITH m
            ORDER BY m.create_time DESC
            LIMIT $n
            RETURN m
            """,
            title=title,
            n=n
        )
        messages = []
        for record in result:
            message = convert_neo4j_message_to_model(record["m"])
            messages.append(message) if message else None
    return messages


def get_latest_messages(title: str, n: int) -> Triplets | None:
    """タイトルを指定して、Cytoscape表示用のMessage、Entity リレーションシップを取得する
        Title -[CONTAIN]-> Message -[CONTAIN] -> Entity"""
    n = n - 1 if n > 1 else 1
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (:Title {{title: $title}})-[:CONTAIN]->(m:Message)
            WITH m
            ORDER BY m.create_time DESC
            LIMIT 1
            MATCH path = (m)-[:FOLLOW*0..{n}]->(m2:Message)
            WITH collect(path) AS paths, collect(m2) AS messages

            UNWIND paths AS p
            UNWIND relationships(p) AS rel
            WITH messages, paths, collect(DISTINCT rel) AS pathRelationships

            UNWIND messages AS message
            OPTIONAL MATCH (message)-[r:CONTAIN]->(n1)
            OPTIONAL MATCH (n1)-[r2]->(n2)

            WITH messages, pathRelationships, collect(DISTINCT n1) AS entity, collect(DISTINCT r) AS r, collect(DISTINCT r2) AS r2, collect(DISTINCT n2) AS entity2
            WITH messages + entity + entity2 AS nodes, pathRelationships + r + r2 AS relationships
            RETURN nodes, relationships
            """,
            title=title,
            n=n
        ).single()

        nodes = set()
        relationships = set()
        if result:
            for node in result["nodes"]:
                nodes.add(convert_neo4j_node_to_model(node))
            for relationship in result["relationships"]:
                relationships.add(convert_neo4j_relationship_to_model(relationship))
            return Triplets(nodes=nodes, relationships=relationships)


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


def get_message_entities(node_ids: list[int]) -> list[TempMemory]:
    """Messageから、Entity -> Entityのノード、閉じたリレーションシップを取得する"""
    with driver.session() as session:
        result = session.run(
            """
            UNWIND $node_ids AS node_id
                MATCH (m:Message)-[:CONTAIN]->(n)
                WHERE id(m) = node_id

            WITH m, collect(n) AS entity
            UNWIND entity as n1
            UNWIND entity as n2
                MATCH (n1)-[r]->(n2)

            WITH m, entity, collect(r) AS relationships
            RETURN collect({message: m, entity: entity, relationships: relationships}) AS result
            """,
            node_ids=node_ids,
        )

        # TempMemory(MessageとTripletsの集合)に変換する。
        temp_memories: list[TempMemory] = []
        for record in result:
            for item in record["result"]:
                message = convert_neo4j_message_to_model(item["message"])
                # 各Messageに対するEntityとRelationshipsをTripletsに格納する。
                entity = [convert_neo4j_node_to_model(e) for e in item["entity"]]
                relationships = [convert_neo4j_relationship_to_model(r) for r in item["relationships"]]
                if entity or relationships:
                    triplets = Triplets(nodes=entity, relationships=relationships)
                else:
                    triplets = None

                # TempMemoryを作成する
                temp_memory = TempMemory(
                    message=message,
                    triplets=triplets,
                )
                temp_memories.append(temp_memory)
        return temp_memories


# Query vector index
async def query_messages(query: str, k: int = 3, threshold: float = 0.9, time_threshold: int = 365) -> list[MessageNode]:
    """ベクトル検索(user_input -> user_input + ai_response)でMessageを検索する。"""
    vector = get_embedding(query)
    # queryNodes内で時間指定を行うことができないので、広めに取得してから、フィルタリングする。
    init_k = k * 10 if k * 10 < 100 else 100
    with driver.session() as session:
        result = session.run(
            """
            CALL db.index.vector.queryNodes('Message', $init_k, $vector)
            YIELD node, score
            WHERE score > $threshold AND node.create_time > datetime() - duration({days: $time_threshold})
            WITH node, score
            LIMIT $k
            RETURN node, score
            """,
            init_k=init_k,
            k=k,
            vector=vector,
            threshold=threshold,
            time_threshold=time_threshold,
        )

        messages = []
        for record in result:
            message = convert_neo4j_message_to_model(record["node"])
            if message:
                score = round(record["score"], 6)
                logger.info(f"score: {score} message: {message.user_input}")
                messages.append(message) if message else None
    return messages


# Store Title and Messages
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


async def store_message(
    input_data: WebSocketInputData,
    ai_response: str,
    user_input_entity: Triplets | None = None,
) -> MessageNode:
    source = input_data.source
    title = input_data.title
    user_input = input_data.user_input
    AI = input_data.AI
    former_node_id = input_data.former_node_id
    current_utc_datetime = datetime.utcnow()
    create_time = current_utc_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
    update_time = create_time

    with driver.session() as session:
        # 親ノードを更新する(update_timeを更新する)
        result = session.run(
            """
            MERGE (a:Title {title: $title})
            ON CREATE SET a.create_time = datetime($create_time), a.update_time = datetime($create_time)
            ON MATCH SET a.update_time = datetime($update_time)
            RETURN id(a) AS title_id
            """,
            title=title,
            create_time=create_time,
            update_time=update_time,
        )
        title_id = result.single()["title_id"]

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
            RETURN b
            """,
            create_time=create_time,
            source=source,
            user_input=user_input,
            user_input_entity=user_input_entity.model_dump_json() if user_input_entity else None,
            AI=AI,
            ai_response=ai_response,
            vector=vector,
        )
        message = result.single()["b"]
        message = convert_neo4j_message_to_model(message)
        logger.info(f"Message Node created. message_id: {message.id}")

        # 親ノード(Title)からのリレーション(CONTAIN)を作成する
        session.run(
            "MATCH (a), (b) WHERE id(a) = $title_id AND id(b) = $new_node_id CREATE (a)-[:CONTAIN]->(b)",
            title_id=title_id,
            new_node_id=message.id,
        )

        # 前のノード(Message)からのリレーション(FOLLOW)と(PRECEDES)を作成
        if former_node_id is not None:
            session.run(
                """MATCH (b), (c)
                        WHERE id(b) = $new_node_id AND id(c) = $former_node_id
                        CREATE (b)-[:FOLLOW]->(c)
                        CREATE (c)-[:PRECEDES]->(b)""",
                new_node_id=message.id,
                former_node_id=former_node_id,
            )

        # Messageからuser_input_entityの各Nodeへのリレーションを作成し、更新対象となったpropertyを保存する。
        if user_input_entity is not None:
            for node in user_input_entity.nodes:
                properties = node.properties if node.properties is not None else {}
                result = session.run(
                    f"""
                        MATCH (b) WHERE id(b) = $new_node_id
                        MATCH (d:{node.label})
                        WHERE d.name = $name OR $name IN d.name_variation
                        CREATE (b)-[r:CONTAIN]->(d)
                        SET r = $props
                        RETURN id(d) as rel_id
                    """,
                    name=node.name,
                    new_node_id=message.id,
                    props=properties,
                )
                rel_id = result.single().get("rel_id")
                if rel_id is None:
                    logger.error(f"Relationship not created. (:Message)-[:CONTAIN]->({node.name}:{node.label})")
    return message


async def pursue_node_update_history(label: str, name: str) -> NodeHistory | None:
    """指定したentityから、node <- [:CONTAIN] - MessageのMessageリストを取得する
    さらに、リレーションシップのプロパティは、その時のノードのプロパティを含むので、
    フィルタリングすることで、ノードの更新履歴を取得することができる。"""
    with driver.session() as session:
        result = session.run(
            f"""
            MATCH (m:Message)-[r]->(n:{label})
            WHERE $name IN n.name_variation OR n.name = $name
            RETURN m, r, n
            """,
            name=name,
        )

        node = None
        messages = []
        relationships = []
        for record in result:
            # Initial Node
            if node is None:
                node = convert_neo4j_node_to_model(record["n"])

            if node is not None:
                # Message Node
                message = convert_neo4j_message_to_model(record["m"])
                messages.append(message) if message else None
                # Relationship
                relationship = convert_neo4j_relationship_to_model(record["r"])
                relationships.append(relationship) if relationship else None

    if node is not None:
        return NodeHistory(node=node, messages=messages, relationships=relationships)
