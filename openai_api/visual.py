# 画像へのリンクを渡す　／　Base64エンコードされた画像を渡す
from openai import OpenAI
from models import ImageChatPrompt

client = OpenAI()


def gpt_4v(
    user_message: str,
    client: OpenAI,
    image_urls: list[str] = None,
    base64_image_urls: list[str] = None,
):
    messages = ImageChatPrompt(
        system_message="これはシステムメッセージです。",
        user_message=user_message,
        image_urls=image_urls,
        base64_image_urls=base64_image_urls,
    ).create_messages()
    print(messages)

    response = client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=messages,
        max_tokens=300,
    )
    response_text = response.choices[0].message.content
    return response_text
