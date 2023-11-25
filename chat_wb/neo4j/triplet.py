import asyncio
import json
import logging
import spacy
from pydantic import BaseModel
from langchain.chains import LLMChain, SequentialChain
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.prompts.chat import (
    AIMessagePromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from chat_wb.models.neo4j import Node, Relation
from chat_wb.main.prompt import (
    COREFERENCE_RESOLUTION_PROMPT,
    EXTRACT_MULTITEMPORALTRIPLET_PROMPT,
)
from chat_wb.neo4j.neo4j import (
    get_all_relationships,
    get_all_relationships_between,
    get_node,
    get_related_nodes_by_relation,
    remove_suffix,
)
from chat_wb.cache import RELATION_SETS
from chat_wb.utils import split_japanese_text
from utils.common import atimer

# ロガー設定
logger = logging.getLogger(__name__)


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

    # print, loggingで表示する際に、full_textを除外する
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
        logging.info(f"node match: {node}")
        if len(nodes) > 1:
            logging.error(f"get nodes: {graph.nodes}")


async def _get_related_nodes_by_relation(graph: TemporalTriplet, node: Node):
    nodes = get_related_nodes_by_relation(
        label=node.label, name=node.name, relation_type=graph.relation.type
    )
    graph.nodes = nodes
    logging.info(f"get related nodes by relation type: {nodes}")


async def _get_node_relations(graph: TemporalTriplet, node: Node):
    relations = get_all_relationships(label=node.label, name=node.name)
    graph.relations = relations
    logging.info(f"relation match: {relations}")


async def _get_node_relations_between(graph: TemporalTriplet):
    relations_between = get_all_relationships_between(
        label1=graph.node1.label,
        label2=graph.node2.label,
        name1=graph.node1.name,
        name2=graph.node2.name,
    )
    graph.relations_between = relations_between
    logging.info(f"relation between match: {relations_between}")


def _get_graph_from_triplet(triplet: TemporalTriplet) -> TemporalTriplet:
    # graphを作成
    graph = TemporalTriplet(triplet=triplet)
    logging.info(f"graph: {graph}")

    # node_labelの一致確認。一致しなければ、nameのみ渡す。
    try:
        graph.node1 = Node(name=graph.name1, label=graph.label1)
    except Exception:
        graph.node1 = Node(name=graph.name1)
    logging.info(f"graph.node1:{graph.node1}")

    if graph.name1 == graph.name2:  # node1とnode2が同じ場合、node2は作成しない。文脈上あり得ないので。
        graph.node2 = None
    else:
        try:
            graph.node2 = Node(name=graph.name2, label=graph.label2)
        except Exception:
            graph.node2 = Node(name=graph.name2)
        logging.info(f"graph.node2:{graph.node2}")

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
        logging.info(f"graph.relation:{graph.relation}")

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
        logging.info(f"triplet: {triplet}")

        # tripletをgraphに変換し、graphをリストに追加
        graph = _get_graph_from_triplet(triplet)
        graphs.append(graph)

    # Neo4jへのクエリレスポンスを取得
    tasks = [query_neo4j(graph) for graph in graphs]
    responses = await asyncio.gather(*tasks)
    graphs = [convert_to_graph_response(response) for response in responses]
    return triplets, graphs


# 約1秒
def coference_resolution_chain() -> LLMChain:
    # tracer = LangChainTracer(project_name="coference_resolution_chain")

    llm = ChatOpenAI(temperature=0.0, model="gpt-3.5-turbo-0613")
    system_prompt = COREFERENCE_RESOLUTION_PROMPT
    system_message_prompt = SystemMessagePromptTemplate.from_template(system_prompt)
    user_prompt = """
    {text}
    """
    human_message_prompt = HumanMessagePromptTemplate.from_template(user_prompt)
    ai_prompt = """
    reference:{reference}
    """
    ai_message_prompt = AIMessagePromptTemplate.from_template(ai_prompt)
    messages_template = [
        system_message_prompt,
        human_message_prompt,
        ai_message_prompt,
    ]

    prompt_template = ChatPromptTemplate.from_messages(messages_template)
    chain = LLMChain(llm=llm, prompt=prompt_template, output_key="context")

    return chain


# 約2秒
# function callingを利用しないのは、エラーを避けるため。
def triplets_chain() -> LLMChain:
    # tracer = LangChainTracer(project_name="triplet_chain")

    llm = ChatOpenAI(temperature=0.0, model="gpt-3.5-turbo-0613")
    system_prompt = EXTRACT_MULTITEMPORALTRIPLET_PROMPT
    system_message_prompt = SystemMessagePromptTemplate.from_template(system_prompt)
    user_prompt = "{context}"
    human_message_prompt = HumanMessagePromptTemplate.from_template(user_prompt)
    messages_template = [
        system_message_prompt,
        human_message_prompt,
    ]

    prompt_template = ChatPromptTemplate.from_messages(messages_template)
    chain = LLMChain(llm=llm, prompt=prompt_template, output_key="triplets")

    return chain


# 約3秒
def sequential_triplet_chain():
    chain1 = coference_resolution_chain()
    chain2 = triplets_chain()
    sequential_chain = SequentialChain(
        chains=[chain1, chain2],
        input_variables=["text", "reference"],
        output_variables=["triplets"],
    )
    return sequential_chain


async def run_sequential_triplet(text: str, reference: str):
    chain = sequential_triplet_chain()
    response = await chain.arun(text=text, reference=reference)
    return response


# @atimer
async def run_sequences(text: str) -> list[dict] | None:
    # 一文に分割
    tokens = split_japanese_text(text)
    logging.info(f"tokens: {tokens}")

    # tripletを抽出(非同期処理)
    tasks = [run_sequential_triplet(text=token, reference=text) for token in tokens]
    responses = await asyncio.gather(*tasks)

    # responseが文字列の場合等、json.loadsできない場合のエラーハンドリング
    results = []
    for token, item in zip(tokens, responses):  # tokenとresponseをzipで組み合わせる
        try:
            json_item = json.loads(item)
            results.extend(json_item if isinstance(json_item, list) else [json_item])
        except json.JSONDecodeError:
            # 有効なJSONでない場合の処理
            logging.error(f"Invalid response for json.loads: {item}")

    # subject, objectの最初の要素（名前）から接尾語を削除
    if not results:
        for data in results:
            data["subject"][0] = remove_suffix(data["subject"][0])
            data["object"][0] = remove_suffix(data["object"][0])
    else:
        results = None
    logging.info(f"results: {results}")  # 出力なしの場合は、Noneを返す。単純質問は、Noneになる傾向。
    return results


# 以下、chain単体テスト用
@atimer
async def run_triplets(text: str) -> list[dict]:
    # tokens = sent_tokenize(text)
    nlp = spacy.load("ja_core_news_sm")
    tokens = [sent.text for sent in nlp(text).sents]

    chain = triplets_chain()
    tasks = [chain.apredict(context=token) for token in tokens]
    response = await asyncio.gather(*tasks)
    result = [item for sublist in map(json.loads, response) for item in sublist]

    return result


# chain単体テスト用
@atimer
async def run_coferences(text: str) -> list[str]:
    nlp = spacy.load("ja_core_news_sm")
    tokens = [sent.text for sent in nlp(text).sents]

    chain = coference_resolution_chain()
    tasks = [chain.apredict(text=token, reference=tokens) for token in tokens]
    response = await asyncio.gather(*tasks)
    return response
