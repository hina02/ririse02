import asyncio
import json
from logging import getLogger
import spacy
from openai import OpenAI
from chat_wb.models.neo4j import Triplets
from chat_wb.main.prompt import (
    COREFERENCE_RESOLUTION_PROMPT,
    EXTRACT_TRIPLET_PROMPT,
)
from chat_wb.neo4j.neo4j import (
    get_node_relationships,
    get_node_relationships_between,
    get_node,
    create_update_append_node,
    create_update_relationship
)
from openai_api.models import ChatPrompt
from chat_wb.utils import split_japanese_text
from chat_wb.models.neo4j import Node, Relationships
from utils.common import atimer

# ロガー設定
logger = getLogger(__name__)

client = OpenAI()


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
    response = client.chat.completions.create(
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
    response = client.chat.completions.create(
        model="gpt-3.5-turbo-1106",
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
        seed=0,  # シード値固定した方が安定するかもしれない。
    )
    return response.choices[0].message.content


async def run_sequences(text: str, reference: str | None = None) -> Triplets | None:
    text = await coference_resolution(text=text, reference=reference)
    response_json = await convert_to_triplets(text=text)

    try:
        response = json.loads(response_json)
    except json.JSONDecodeError:        # 有効なJSONでない場合の処理
        logger.error(f"Invalid response for json.loads: {response}")
        return None  # 出力なしの場合は、Noneを返す。単純質問は、Noneになる傾向。
    triplets = Triplets.create(response)
    logger.info(f"triplets: {triplets}")
    return triplets


@atimer
async def get_memory_from_triplet(triplets: Triplets) -> tuple[Triplets, Triplets]:
    # Neo4jへのクエリレスポンスを取得 1回で1秒程度
    # functionにする(つまりAIがどれを使うか選択)ことを検討。ノード取得を使うか？を、各nodeに対して判断する。
    tasks = []
    # nodeの取得
    for node in triplets.nodes:
        tasks.append(get_node(node.label, node.name))
        # nodeが持つすべてのrealtionを取得
        tasks.append(get_node_relationships(node.label, node.name))

    if triplets.relationships:
        for relationship in triplets.relationships:
            # node1とnode2間のrelationを取得
            tasks.append(get_node_relationships_between(
                relationship.start_node_label,
                relationship.end_node_label,
                relationship.start_node,
                relationship.end_node))

    responses = await asyncio.gather(*tasks)
    # 結果を、nodesとrelationsに整理する。
    nodes = []
    relationships = []
    for response in responses:
        if response and isinstance(response[0], Node):
            nodes.extend(response)
        elif response and isinstance(response[0], Relationships):
            relationships.extend(response)
    logger.info(f"nodes: {nodes}")
    logger.info(f"relations: {relationships}")
    query_results = Triplets(nodes=nodes, relationships=relationships)

    return query_results


def store_memory_from_triplet(triplets: Triplets):
    for node in triplets.nodes:
        create_update_append_node(node)
    if triplets.relationships:
        for relation in triplets.relationships:
            create_update_relationship(relation)
