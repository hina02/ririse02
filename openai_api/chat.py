import asyncio
from openai import OpenAI, AsyncOpenAI
from models import ChatPrompt
from utils.common import timer, atimer


memory = []  # 会話の記憶


@timer
def chat(
    system_message: str,
    user_message: str,
    client: OpenAI,
    model: str = "gpt-3.5-turbo-1106",
):
    messages = ChatPrompt(
        system_message=system_message,
        user_message=user_message,
        assistant_message="".join(memory),
    ).create_messages()  # 会話の記憶を追加

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=80,
        temperature=0.7,
    )
    response_text = response.choices[0].message.content
    memory.append(response_text)
    return response_text


# シード値固定
def seed_chat(
    system_message: str,
    user_message: str,
    client: OpenAI,
    model: str = "gpt-3.5-turbo-1106",
    seed: int = None,
):
    messages = ChatPrompt(
        system_message=system_message,
        user_message=user_message,
    ).create_messages()

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=80,
        temperature=0.7,
        seed=seed,  # シード値固定
    )
    response_text = response.choices[0].message
    system_fingerprint = response.system_fingerprint  # 足跡の取得
    memory.append(response_text.content)
    print(system_fingerprint)
    return response


# print(seed_chat("", "和歌を作って。"))


# 非同期処理
@atimer
async def async_chat(user_messages: list[str], async_client: AsyncOpenAI) -> None:
    tasks = [
        asyncio.create_task(_achat(user_message, async_client))
        for user_message in user_messages
    ]
    await asyncio.gather(*tasks)


@atimer
async def _achat(
    user_message: str, async_client: AsyncOpenAI, system_message="initialize chat"
) -> None:
    messages = ChatPrompt(
        system_message=system_message,
        user_message=user_message,
    ).create_messages()

    chat_completion = await async_client.chat.completions.create(
        model="gpt-3.5-turbo", messages=messages
    )
    print(chat_completion.choices[0].message.content)
