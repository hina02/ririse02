import asyncio
import json
from logging import getLogger
import openai
from openai import AsyncOpenAI
from chat_wb.models import Triplets, Node, Relationships, TempMemory
from chat_wb.main.prompt import (
    CODE_SUMMARIZER_PROMPT,
    DOCS_SUMMARIZER_PROMPT,
    EXTRACT_TRIPLET_PROMPT,
    EXTRACT_ENTITY_PROMPT,
    TEXT_TRIAGER_PROMPT,
)
from chat_wb.neo4j.neo4j import (
    get_node_relationships,
    get_node,
    create_update_node,
    create_update_relationship,
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

    # triage summerize function
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
            model="gpt-4-1106-preview",
            messages=messages,
            max_tokens=16,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        response_json = response.choices[0].message.content
        result = json.loads(response_json).get("type")
        self.user_input_type = result  # 判定結果を保存
        logger.info(result)
        return result

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
            max_tokens=512,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        response_json = response.choices[0].message.content
        logger.info(response_json)
        return response_json

    async def summerize_docs(self, text: str):
        """Summerize long document for burden of triplets"""
        system_prompt = DOCS_SUMMARIZER_PROMPT
        user_prompt = text
        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
        ).create_messages()

        response = await self.client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=512,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        response_json = response.choices[0].message.content
        logger.info(response_json)
        return response_json

    async def summerize_chat(self, text: str):
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
        system_prompt = EXTRACT_TRIPLET_PROMPT.format(user=self.user_name, ai=self.ai_name)
        user_prompt = text
        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
        ).create_messages()

        # response生成
        response = await self.client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=messages,
            temperature=0.0,
            max_tokens=2048,
            response_format={"type": "json_object"},
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
        logger.info(f"response_json: {response_json}")
        # convert to triplets model
        try:
            response = json.loads(response_json)
        except json.JSONDecodeError:        # 有効なJSONでない場合の処理
            logger.error("Invalid response for json.loads")
            return None
        triplets = Triplets.create(response, self.user_name, self.ai_name)
        if not triplets.nodes and not triplets.relationships:
            triplets = None
        return triplets

    @atimer
    async def extract_entites(self, text: str) -> list[str] | None:
        """user_inputから、entityを抽出する。0.5～1.5秒程度。"""
        # prompt
        system_prompt = EXTRACT_ENTITY_PROMPT
        user_prompt = text
        messages = ChatPrompt(
            system_message=system_prompt,
            user_message=user_prompt,
        ).create_messages()

        # response生成
        response = await self.client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            temperature=0.0,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        try:
            entity = json.loads(response.choices[0].message.content).get("Entity")
            logger.info(entity)
            return entity
        except json.JSONDecodeError:
            logger.error("Invalid JSON response")
            return None

    @staticmethod
    async def store_memory_from_triplet(triplets: Triplets):
        """user_input_entityに基づいて、Neo4jにノード、リレーションシップを保存"""
        for node in triplets.nodes:
            create_update_node(node)
        if triplets.relationships:
            for relation in triplets.relationships:
                create_update_relationship(relation)
