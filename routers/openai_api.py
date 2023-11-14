from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
import uuid
import logging
from openai import OpenAI, AsyncOpenAI
from openai_api.chat import chat, async_chat
from openai_api.jsonmode import output_json, output_json_to_neo4j
from openai_api.visual import gpt4v


openai_api_router = APIRouter()


class Gpt4vRequest(BaseModel):
    user_message: str
    image_urls: list[str] | None = None
    base64_image_urls: list[str] | None = None


class OpenAIClient:
    def __init__(self, user_id: str | None = None):
        self.client = OpenAI(  # max_retries = 2 default
            # timeout = 60.0 default
        )  # defaults to os.environ.get("OPENAI_API_KEY")
        self.async_clinent = AsyncOpenAI()
        self.user_id = user_id


clients: dict = {}


def get_openai_client(request: Request):
    if "user_id" not in request.session:
        request.session["user_id"] = str(uuid.uuid4())  # Generate a new user_id
    user_id = request.session["user_id"]

    if user_id not in clients:
        clients[user_id] = OpenAIClient(user_id)
        logging.info(f"initialize user_id: {user_id}")
    return clients[user_id].client


@openai_api_router.get("/chat")
def chat_api(
    user_message: str, client: OpenAIClient = Depends(get_openai_client)
) -> str:
    result = chat("initialize chat.", user_message, client=client)
    logging.info(f"User ID: {client.user_id}")
    return result


@openai_api_router.get("/async_chat")
async def async_chat_api(
    user_message: str, k: int = 3, client: OpenAIClient = Depends(get_openai_client)
):
    """非同期処理のテスト 3回同じ入力を与えて、3回同じ出力が得られることを確認する"""
    user_messages = []
    user_messages.extend([user_message] * k)
    result = await async_chat(user_messages, client.async_clinent)
    return result


@openai_api_router.get("/output_json")
async def output_json_api(
    user_message: str, client: OpenAIClient = Depends(get_openai_client)
):
    result = output_json(user_message, client=client)
    return result  # DOCSで確認したい場合は、json.loads(result)


@openai_api_router.get("/output_json_to_neo4j")
async def output_json_to_neo4j_api(
    user_message: str, client: OpenAIClient = Depends(get_openai_client)
):
    """サンプルテキスト:
    「彩澄りりせ」は、ぴた声シリーズのキャラクターとして誕生した16歳の女の子です。彩澄しゅおのお姉さんです。"""
    result = output_json_to_neo4j(user_message, client=client)
    return result


@openai_api_router.post("/gpt4v")
async def gpt4v_api(
    request: Gpt4vRequest,
    client: OpenAIClient = Depends(get_openai_client),
):
    """サンプル画像URL:
    https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg
    """
    user_message = request.user_message
    image_urls = request.image_urls
    base64_image_urls = request.base64_image_urls

    result = gpt4v(
        user_message,
        client=client,
        image_urls=image_urls,
        base64_image_urls=base64_image_urls,
    )
    return result
