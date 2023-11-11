from pydantic import BaseModel, validator
from typing import Literal
import base64


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
        messages = [
            Message(role="system", content=self.system_message),
            Message(role="user", content=self.user_message),
        ]
        if self.assistant_message is not None:
            messages.append(Message(role="assistant", content=self.assistant_message))
        return messages


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
            self.user_message.extend(
                [{"type": "image_url", "image_url": {"url": image_url}}]
            )

    def add_base64_images(self, base64_image_urls: list[str]) -> None:
        # user_messageの変換
        self.user_message = [{"type": "text", "text": self.user_message}]

        # base64エンコードされた画像を追加
        for base64_image_url in base64_image_urls:
            base64_image = encode_image(base64_image_url)
            base64_data = f"data:image/jpeg;base64,{base64_image}"
            self.user_message.extend(
                [{"type": "image_url", "image_url": {"url": base64_data}}]
            )
