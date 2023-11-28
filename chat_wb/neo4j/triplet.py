import asyncio
import json
from logging import getLogger
import spacy
from pydantic import BaseModel
from openai import AsyncOpenAI
from chat_wb.models.neo4j import Node, Relation
from chat_wb.main.prompt import (
    COREFERENCE_RESOLUTION_PROMPT,
    EXTRACT_TRIPLET_PROMPT,
)
from chat_wb.neo4j.neo4j import (
    get_all_relationships,
    get_all_relationships_between,
    get_node,
    get_related_nodes_by_relation,
    remove_suffix,
)
from openai_api.models import ChatPrompt
from chat_wb.cache import RELATION_SETS
from chat_wb.utils import split_japanese_text
from utils.common import atimer

# ロガー設定
logger = getLogger(__name__)


class TemporalTriplet(BaseModel):
    # tripletからの情報
    triplet: dict
    label1: str
    name1: str
    label2: str
    name2: str
    relation_type: str
    raw_text: str  # 分割text
    full_text: str  # 全文
    time: str | None

    # graphサーチして得たid,プロパティ
    node1: Node | None  # node1のidとプロパティ
    node2: Node | None  # node2のidとプロパティ
    relation: Relation | None  # relationのidとプロパティ

    # graphサーチして得た関連node、relationship
    nodes: list[Node] | None  # node1,relationから複数のnodeを取得する
    relations: list[
        Relation
    ] | None  # node1から複数のrelationとノードを取得する     has,located_at,belong等のプロパティ情報に限定する方がいいか。
    relations_between: list[Relation] | None  # node1とnode2から複数のrelationを取得する

    __fields_set__ = set(
        [
            "triplet",
            "label1",
            "name1",
            "label2",
            "name2",
            "relation_type",
            "raw_text",
            "full_text",
            "time",
            "node1",
            "node2",
            "relation",
            "nodes",
            "relations",
        ]
    )

    def __init__(self, triplet: dict, raw_text: str, full_text: str):
        self.triplet = triplet
        self.label1 = triplet["subject"][1]
        self.name1 = triplet["subject"][0]
        self.label2 = triplet["object"][1]
        self.name2 = triplet["object"][0]
        self.relation_type = triplet["predicate"][1]
        self.raw_text = raw_text
        self.full_text = full_text
        self.time = triplet.get("time")  # "time"キーがない場合はNoneを返す

        self.node1 = None
        self.node2 = None
        self.relation = None
        self.nodes = None
        self.relations = None
        self.relations_between = None

    # print, loggerで表示する際に、full_textを除外する
    def __str__(self):
        fields = {
            k: v
            for k, v in self.model_dump().items()
            if k not in ["full_text", "raw_text"]
        }
        return f"TemporalTriplet({fields})"


# 最終レスポンスを、graphサーチの結果に変換する
class ResponseGraph(BaseModel):
    # graphサーチして得たid,プロパティ
    node1: Node | None
    node2: Node | None
    relation: Relation | None

    # graphサーチして得た関連node、relationship
    nodes: list[Node] | None
    relations: list[Relation] | None
    relations_between: list[Relation] | None


def convert_to_graph_response(triplet: TemporalTriplet) -> ResponseGraph:
    return ResponseGraph(
        node1=triplet.node1,
        node2=triplet.node2,
        relation=triplet.relation,
        nodes=triplet.nodes,
        relations=triplet.relations,
        relations_between=triplet.relations_between,
    )


# Neo4j関連の関数
async def _get_node(graph: TemporalTriplet, node: Node):
    nodes = get_node(name=node.name, label=node.label)
    if nodes:
        node_obj = nodes[0]
        node.id = node_obj.get("id")
        node.properties = node_obj.get("properties")
        logger.info(f"node match: {node}")
        if len(nodes) > 1:
            logger.error(f"get nodes: {graph.nodes}")


async def _get_related_nodes_by_relation(graph: TemporalTriplet, node: Node):
    nodes = get_related_nodes_by_relation(
        label=node.label, name=node.name, relation_type=graph.relation.type
    )
    graph.nodes = nodes
    logger.info(f"get related nodes by relation type: {nodes}")


async def _get_node_relations(graph: TemporalTriplet, node: Node):
    relations = get_all_relationships(label=node.label, name=node.name)
    graph.relations = relations
    logger.info(f"relation match: {relations}")


async def _get_node_relations_between(graph: TemporalTriplet):
    relations_between = get_all_relationships_between(
        label1=graph.node1.label,
        label2=graph.node2.label,
        name1=graph.node1.name,
        name2=graph.node2.name,
    )
    graph.relations_between = relations_between
    logger.info(f"relation between match: {relations_between}")


def _get_graph_from_triplet(triplet: TemporalTriplet) -> TemporalTriplet:
    # graphを作成
    graph = TemporalTriplet(triplet=triplet)
    logger.info(f"graph: {graph}")

    # node_labelの一致確認。一致しなければ、nameのみ渡す。
    try:
        graph.node1 = Node(name=graph.name1, label=graph.label1)
    except Exception:
        graph.node1 = Node(name=graph.name1)
    logger.info(f"graph.node1:{graph.node1}")

    if graph.name1 == graph.name2:  # node1とnode2が同じ場合、node2は作成しない。文脈上あり得ないので。
        graph.node2 = None
    else:
        try:
            graph.node2 = Node(name=graph.name2, label=graph.label2)
        except Exception:
            graph.node2 = Node(name=graph.name2)
        logger.info(f"graph.node2:{graph.node2}")

    # relation_typeの一致確認
    # 読み取りの場合、contentは不要。DBからのデータで上書きされる。
    # tripletのものが入るならそれを採用する。 # 入らない場合、node1とnode2のlabelから推測する
    content = [str(graph.raw_text)]
    try:
        graph.relation = Relation(type=graph.relation_type, content=content)
    except Exception:
        # 入らない場合、node1とnode2のlabelから推測する
        if graph.node1 and graph.node1.label and graph.node2 and graph.node2.label:
            relation_type = RELATION_SETS.get((graph.node1.label, graph.node2.label))
            graph.relation = Relation(type=relation_type, content=content)
        else:
            pass  # node1,node2のラベルが適切でない場合、relationはNoneにする

    # relationが存在し、timeがある場合、timeをrelationに追加する
    if hasattr(graph, "relation"):
        if graph.time:
            graph.relation.time = graph.time
        logger.info(f"graph.relation:{graph.relation}")

    return graph


# 1回で1秒程度
async def query_neo4j(graph) -> TemporalTriplet:
    """
    非同期処理を使用してNeo4jからデータを取得する関数。
    """
    tasks = []
    tasks.append(_get_node(graph, graph.node1))

    if graph.node2:
        tasks.append(_get_node(graph, graph.node2))
        tasks.append(_get_node_relations_between(graph))

    tasks.append(_get_related_nodes_by_relation(graph, graph.node1))
    tasks.append(_get_node_relations(graph, graph.node1))

    await asyncio.gather(*tasks)

    return graph


@atimer
async def get_graph_from_triplet(text: str) -> tuple[list[dict], list[ResponseGraph]]:
    # tripletのリストを抽出
    triplets = await run_sequences(text)  # list[dict]
    if triplets is None:
        return None  # 出力なしの場合は、Noneを返す。
    # tripletからの情報をgraphに格納
    graphs = []
    for triplet in triplets:
        logger.info(f"triplet: {triplet}")

        # tripletをgraphに変換し、graphをリストに追加
        graph = _get_graph_from_triplet(triplet)
        graphs.append(graph)

    # Neo4jへのクエリレスポンスを取得
    tasks = [query_neo4j(graph) for graph in graphs]
    responses = await asyncio.gather(*tasks)
    graphs = [convert_to_graph_response(response) for response in responses]
    return triplets, graphs


client = AsyncOpenAI()


@atimer
async def coference_resolution(text: str, reference: str | None = None):
    # prompt
    system_prompt = COREFERENCE_RESOLUTION_PROMPT
    user_prompt = f"{text}"
    ai_prompt = f"reference:{reference}"    # 分割したテキストの参考にreferenceを渡していたが、JSONModeでほぼ不要になった。
    messages = ChatPrompt(
        system_message=system_prompt,
        user_message=user_prompt,
        assistant_message=ai_prompt,
    ).create_messages()

    # response生成
    response = await client.chat.completions.create(
        model="gpt-3.5-turbo-1106",
        messages=messages,
        temperature=0.0,
    )
    return response.choices[0].message.content


@atimer
async def convert_to_triplets(text: str):
    """example output "Mary is nurse. Tom married Mary. "
    {
    "Nodes": [
        {"label": "Person", "name": "Mary", "properties": {"job": "nurse"}},
        {"label": "Person", "name": "Tom", "properties": {}}
    ],
    "Relationships": [
        {"start_node": "Tom", "end_node": "Mary", "type": "MARRIED_TO", "properties": {}}
    ]
    }
    """
    # prompt
    system_prompt = EXTRACT_TRIPLET_PROMPT
    user_prompt = f"{text}"
    messages = ChatPrompt(
        system_message=system_prompt,
        user_message=user_prompt,
    ).create_messages()

    # response生成
    response = await client.chat.completions.create(
        model="gpt-3.5-turbo-1106",
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
        seed=0,  # シード値固定した方が安定するかもしれない。
    )
    return response.choices[0].message.content


async def run_sequential_triplet(text: str, reference: str):
    text = await coference_resolution(text=text, reference=reference)
    response = await convert_to_triplets(text=text)
    return response


async def run_sequences(text: str) -> list[dict] | None:
    response = await run_sequential_triplet(text=text, reference=None)

    try:
        data = json.loads(response)
    except json.JSONDecodeError:        # 有効なJSONでない場合の処理
        logger.error(f"Invalid response for json.loads: {data}")
        return None  # 出力なしの場合は、Noneを返す。単純質問は、Noneになる傾向。

    # Nodeのnameから接尾語を削除
    for node in data['Nodes']:
        node['name'] = remove_suffix(node['name'])
    # Relationshipsのstart_nodeとend_nodeに対してremove_suffixを適用
    if 'Relationships' in data:
        for relationship in data['Relationships']:
            relationship['start_node'] = remove_suffix(relationship['start_node'])
            relationship['end_node'] = remove_suffix(relationship['end_node'])

    return data
