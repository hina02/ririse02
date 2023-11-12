# 画像へのリンクを渡す　／　Base64エンコードされた画像を渡す
from openai import OpenAI
from models import ImageChatPrompt

client = OpenAI()


def gpt4v(
    user_message: str,
    client: OpenAI,
    image_urls: list[str] = None,
    base64_image_urls: list[str] = None,
):
    messages = ImageChatPrompt(
        system_message="Simply answer about the screenshot in 140 tokens or less.",
        user_message=user_message,
        assistant_message="このスクリーンショットに表示されたテキストは、次の通りです。",
        image_urls=image_urls,
        base64_image_urls=base64_image_urls,
    ).create_messages()

    response = client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=messages,
        max_tokens=140,
    )
    response_text = response.choices[0].message.content
    return response_text
