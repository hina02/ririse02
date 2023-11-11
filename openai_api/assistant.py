from openai import OpenAI
from openai.types.beta.assistant import Assistant  # アシスタントの型
from openai.types.beta.thread import Thread  # スレッドの型
from openai.types.beta.threads import ThreadMessage  # メッセージの型

from openai import AsyncOpenAI

aclient = AsyncOpenAI()  # 非同期クライアント

client = OpenAI()


# モデルファイルの読み取り
# file = client.files.create(
#     file=open("speech.py", "rb"),
#     purpose="assistants"    #fileモジュールは、fine-tuneとassistantsをサポートする模様
# )

# アシスタントの作成
# アシスタントごとに、20個までのファイル（各最大512MB）を添付できる。
assistant = client.beta.assistants.create(
    name="Math Tutor",
    model="gpt-4-1106-preview",
    description="Personal math tutor",
    instructions="You are a personal math tutor. Write and run code to answer math questions.",
    tools=[
        {"type": "code_interpreter"}
    ],  # ツールの指定(retrieval, code_interpreter, function)
    # file_ids=[file.id]
)

# スレッドの作成
# 現時点では、messagesはrole:userのみサポート
# metadataに、追加情報を与えられるのが素晴らしい。
thread = client.beta.threads.create()
print(f"thread_id: {thread.id}")

# ユーザー入力の作成
message = client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="I need to solve the equation `3x + 11 = 14`. Can you help me?",
    # metadata={"x1": -2, "x2": 3}
)
print(f"message_id: {message.id}")

# AIアシスタントの実行
# ツールの呼び出しなどを判断して最適な回答を決定。
# （Runの作成中に追加指示を渡すこともできる）
run = client.beta.threads.runs.create(
    thread_id=thread.id,
    assistant_id=assistant.id,
    instructions="Please address the user as Jane Doe. The user has a premium account.",
)
print(f"run_id: {run.id}")


# Retrieve 実行結果を取得
# Runの実行内容を取得する場合は、run_idを指定する。
run_plan = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
run_status = run_plan.status
print(f"run_status: {run_status}")  # queued, running, completed, failed, timed_out
# run_assistant_id = run_result.assistant_id


# Messageの結果を取得する場合は、message_idを指定する。
message = client.beta.threads.messages.retrieve(
    thread_id=thread.id, message_id=message.id
)
print(type(message))
# Extract the message content
message_content = message.content[0].text
created_at = message.created_at
annotations = message_content.annotations
citations = []
print(f"message_content: {message_content}")
print(f"created_at: {created_at}")
print(f"annotations: {annotations}")


run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
messages = client.beta.threads.messages.list(thread_id=thread.id)
print(messages)
