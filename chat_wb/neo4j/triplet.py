import asyncio
import json
from logging import getLogger
import openai
from openai import AsyncOpenAI
from chat_wb.models import Triplets, Node, Relationships, TempMemory
from chat_wb.main.prompt import (
    CODE_SUMMARIZER_PROMPT,
    DOCS_COMPRESSER_PROMPT,
    DOCS_CONVERTER_PROMPT,
    COREFERENCE_RESOLUTION_PROMPT,
    EXTRACT_TRIPLET_PROMPT,
    TEXT_TRIAGER_PROMPT,
)
from chat_wb.neo4j.neo4j import (
    get_node_relationships,
    get_node_relationships_between,
    get_node,
    create_update_node,
    create_update_relationship
)
from openai_api.models import ChatPrompt
from utils.common import atimer

# ロガー設定
logger = getLogger(__name__)


class TripletsConverter():
    """OpenAI APIを用いて、textをtripletsに変換するクラス"""
    def __init__(self, client: AsyncOpenAI | None = None,  user_name: str = "彩澄しゅお", ai_name: str = "彩澄りりせ"):
        self.client = AsyncOpenAI() if client is None else client
        self.user_name = user_name
        self.ai_name = ai_name
        self.user_input_type = "question"  # questionの時は、neo4jに保存しない。

    async def summerize_code(self, text: str):
        """Summerize code block for burden of triplets"""
        system_prompt = CODE_SUMMARIZER_PROMPT
        user_prompt = text
        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
        ).create_messages()

        response = await self.client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=240,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        response_json = response.choices[0].message.content
        logger.info(response_json)
        return response_json

    async def compress_docs(self, text: str):
        """Compress long document to 1 sentence."""
        system_prompt = DOCS_COMPRESSER_PROMPT
        user_prompt = text
        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
        ).create_messages()

        response = await self.client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=240,
            temperature=0.3,
        )
        response_json = response.choices[0].message.content
        logger.info(response_json)
        return response_json

    async def convert_docs(self, text: str):
        """extruct triplets from compressed document"""
        system_prompt = DOCS_CONVERTER_PROMPT
        user_prompt = text
        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
        ).create_messages()

        response = await self.client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=240,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        response_json = response.choices[0].message.content
        logger.info(response_json)
        return response_json

    async def summerize_docs(self, text: str):
        """Summerize long document for burden of triplets"""
        result = await self.compress_docs(text=text)
        logger.info(result)
        response_json = await self.convert_docs(text=result)
        return response_json

    async def summerize_chat(self, text: str):
        """Regular method for extruct triplets"""
        result = await self.coference_resolution(text=text)
        logger.info(result)
        response_json = await self.convert_to_triplets(text=result)
        return response_json

    # triage function
    async def triage_text(self, text: str) -> str:
        """triage text to chat, question, code, document"""
        # moderation
        moderation_result = openai.moderations.create(input=text).results[0]
        if moderation_result.flagged:
            logger.info("openai policy violation")
            return "openai_policy_violation"

        # triage text
        system_prompt = TEXT_TRIAGER_PROMPT
        user_prompt = text
        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
        ).create_messages()

        response = await self.client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=20,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        response_json = response.choices[0].message.content
        result = json.loads(response_json).get("type")
        self.user_input_type = result  # 判定結果を保存
        logger.info(result)
        return result


    async def coference_resolution(self, text: str):
        """Output format is {"change": true or false, "changed_sentence": ""}"""
        # prompt
        system_prompt = COREFERENCE_RESOLUTION_PROMPT.format(user=self.user_name)
        user_prompt = f"""{text}"""
        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
            short_memory=self.short_memory if self.short_memory else None,  # 会話履歴を利用して、補正強化。
        ).create_messages()

        # response生成
        response = await self.client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        # 修正がない場合は元のテキストを返す。
        response_json = response.choices[0].message.content
        try:
            response = json.loads(response_json)
            logger.info(response)
            if response.get("change"):
                return response.get("changed_sentence")
            else:
                return text
        except Exception as e:
            logger.error(f"Invalid response for json.loads {e}")
            return text

    async def convert_to_triplets(self, text: str):
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
        response = await self.client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
            seed=0,  # シード値固定した方が安定するかもしれない。
        )
        return response.choices[0].message.content

    @atimer
    async def run_sequences(self, text: str, short_memory: list[TempMemory] | None = None) -> Triplets | None:        
        # for conference_resolution
        self.short_memory = short_memory

        # convert to triplets
        if self.user_input_type == "code":
            response_json = await self.summerize_code(text=text)
        elif self.user_input_type == "document":
            response_json = await self.summerize_docs(text=text)
        else:
            response_json = await self.summerize_chat(text=text)

        # convert to triplets model
        try:
            response = json.loads(response_json)
        except json.JSONDecodeError:        # 有効なJSONでない場合の処理
            logger.error("Invalid response for json.loads")
            return None  # 出力なしの場合は、Noneを返す。単純質問は、Noneになる傾向。
        triplets = Triplets.create(response, self.user_name, self.ai_name)
        logger.info(f"triplets: {triplets}")
        return triplets

    @staticmethod
    async def get_memory_from_triplet(triplets: Triplets) -> Triplets:
        """user_input_entityに基づいて、Neo4jへのクエリレスポンスを取得 1回で1秒程度"""
        tasks = []
        # nodeの取得
        for node in triplets.nodes:
            tasks.append(get_node(node.label, node.name))
            # nodeが持つすべてのrealtion(Messageを除く)を取得
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
        logger.debug(f"nodes: {nodes}")
        logger.debug(f"relations: {relationships}")
        query_results = Triplets(nodes=nodes, relationships=relationships)

        return query_results

    @staticmethod
    async def store_memory_from_triplet(triplets: Triplets):
        """user_input_entityに基づいて、Neo4jにノード、リレーションシップを保存"""
        for node in triplets.nodes:
            create_update_node(node)
        if triplets.relationships:
            for relation in triplets.relationships:
                create_update_relationship(relation)
