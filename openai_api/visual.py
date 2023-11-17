# 画像へのリンクを渡す　／　Base64エンコードされた画像を渡す
from openai import OpenAI
from models.chat import ImageChatPrompt

client = OpenAI()


def gpt4v(
    user_message: str,
    client: OpenAI,
    image_urls: list[str] = None,
    base64_image_urls: list[str] = None,
):
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
