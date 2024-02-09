import base64
import uuid
from logging import getLogger
from typing import Literal

from fastapi import APIRouter, Depends, Request
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, validator

logger = getLogger(__name__)

openai_api_router = APIRouter()


class OpenAIClient:
    def __init__(self, user_id: str | None = None):
        self.client = OpenAI(  # max_retries = 2 default
            # timeout = 60.0 default
        )  # defaults to os.environ.get("OPENAI_API_KEY")
        self.async_clinent = AsyncOpenAI()
        self.user_id = user_id


clients: dict = {}


class Gpt4vRequest(BaseModel):
    user_message: str
    image_urls: list[str] | None = None
    base64_image_urls: list[str] | None = None


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str | list[dict]

    @validator("content")
    def check_content(cls, v, values, **kwargs):
        if values["role"] in ["system", "assistant"] and not isinstance(v, str):
            raise ValueError("content must be str when role is system or assistant")
        return v


class ChatPrompt(BaseModel):
    system_message: str
    user_message: str | list[dict]
    assistant_message: str | None = None

    def create_messages(self) -> list:
        """system, short_memory([user,assistant] * n), user, assistant"""
        messages = []
        messages.append(Message(role="system", content=self.system_message))
        # # short_memoryから、user, assistantのメッセージ履歴を取得
        # for temp_memory in self.short_memory:
        #     messages.append(Message(role="user", content=f"{temp_memory.message.create_time}: {temp_memory.message.user_input}"))
        #     messages.append(Message(role="assistant", content=f"{temp_memory.message.ai_response}"))

        # 現在のuser, assistantのメッセージを追加
        messages.append(Message(role="user", content=self.user_message))
        if self.assistant_message is not None:
            messages.append(Message(role="assistant", content=self.assistant_message))

        return messages


def get_openai_client(request: Request):
    if "user_id" not in request.session:
        request.session["user_id"] = str(uuid.uuid4())  # Generate a new user_id
    user_id = request.session["user_id"]

    if user_id not in clients:
        clients[user_id] = OpenAIClient(user_id)
        logger.info(f"initialize user_id: {user_id}")
    return clients[user_id].client


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

    messages = ImageChatPrompt(
        system_message="画面左のセリフ（日本語訳）と、描かれている内容を簡潔に断定的に、サウンドノベルゲーム風に回答してください。回答は140トークンに収めること。",
        user_message=user_message,
        assistant_message="",
        image_urls=image_urls,
        base64_image_urls=base64_image_urls,
    ).create_messages()

    response = client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=messages,
        max_tokens=240,
    )
    response_text = response.choices[0].message.content
    return response_text


# 画像をBase64にエンコードするヘルパー関数
def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


class ImageChatPrompt(ChatPrompt):
    """画像のWebURL或いは、ローカルパスを渡して、画像を追加する"""

    image_urls: list[str] | None = None
    base64_image_urls: list[str] | None = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.image_urls:
            self.add_images(self.image_urls)
        if self.base64_image_urls:
            self.add_base64_images(self.base64_image_urls)

    def add_images(self, image_urls: list[str]) -> None:
        # user_messageの変換
        self.user_message = [{"type": "text", "text": self.user_message}]
        # 画像URLを追加
        for image_url in image_urls:
            self.user_message.extend([{"type": "image_url", "image_url": {"url": image_url}}])

    def add_base64_images(self, base64_image_urls: list[str]) -> None:
        # user_messageの変換
        self.user_message = [{"type": "text", "text": self.user_message}]

        # base64エンコードされた画像を追加
        for base64_image_url in base64_image_urls:
            base64_image = encode_image(base64_image_url)
            base64_data = f"data:image/jpeg;base64,{base64_image}"
            self.user_message.extend([{"type": "image_url", "image_url": {"url": base64_data}}])
