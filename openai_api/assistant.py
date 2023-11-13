import openai
import requests
from openai import OpenAI
from openai.types.beta.assistant import Assistant  # アシスタントの型
from openai.types.beta.thread import Thread  # スレッドの型
from openai.types.beta.threads import ThreadMessage  # メッセージの型
import os 
import time
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel

os.environ["OPENAI_API_KEY"] ="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"
openai_api_key: str = os.getenv("OPENAI_API_KEY")

# AsyncOpenAIで、各クラス同様にある。
client = OpenAI()


class AssistantManager:
    def __init__(self, client: OpenAI):
        self.client = client
        self.assistants = client.beta.assistants
        # openai apiリクエストのヘッダー
        self.__headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "OpenAI-Beta": "assistants=v1"
        }
        self.details = self.get_assistants()

    # get
    def get_assistant_ids(self):
        response = requests.get("https://api.openai.com/v1/assistants?order=desc&limit=20", headers=self.__headers)
        response_data = response.json()["data"]
        assistant_ids = [data["id"] for data in response_data]
        return assistant_ids

    def get_assistant_details(self, asst_id: str):
        response = requests.get(f"https://api.openai.com/v1/assistants/{asst_id}", headers=self.__headers)
        return response.json()

    def get_assistants(self):
        asst_ids = self.get_assistant_ids()
        assistants = []
        for asst_id in asst_ids:
            assistant = self.get_assistant_details(asst_id)
            assistants.append(assistant)
        return assistants

    # create
    def create_assistant(self, name: str, description: str, instructions: str, tools: list[dict] | None = None, file_ids: list[str] | None = None):
        data = {
            "name": name,
            "model": "gpt-4-1106-preview",
            "description": description,
            "instructions": instructions,
        }
        if tools is not None:
            data["tools"] = tools
        if file_ids is not None:
            data["file_ids"] = file_ids
        assistant = self.assistants.create(**data)
        return assistant

    # update
    def update_assistant(self, asst_id: str, instructions: str, tools: list[dict] | None = None, file_ids: list[str] | None = None):
        data = {
            "model": "gpt-4-1106-preview",
            "instructions": instructions,
        }
        if tools is not None:
            data["tools"] = tools
        if file_ids is not None:
            data["file_ids"] = file_ids
        response = requests.post(f"https://api.openai.com/v1/assistants/{asst_id}", headers=self.__headers, json=data)
        return response.json()

    # delete
    def delete_assistant(self, asst_id: str):
        response = requests.delete(f"https://api.openai.com/v1/assistants/{asst_id}", headers=self.__headers)
        return response

# モデルファイルの読み取り
# file = client.files.create(
#     file=open("speech.py", "rb"),
#     purpose="assistants"    #fileモジュールは、fine-tuneとassistantsをサポートする模様
# )

# スレッドの作成
# Threadsは、Assistantとは独立。AssistantはRun時に指定する。
# 現時点では、messagesはrole:userのみサポート
# metadata(16までのkey value)に、追加情報を与えられるのが素晴らしい。
# retrieve, update, delete, create_and_runもサポート
class ThreadManager:
    def __init__(self, client: OpenAI):
        self.client = client
        self.threads = client.beta.threads

    def create_thread(self, metadata: dict | None = None):
        if metadata is not None:
            thread = self.threads.create(metadata=metadata)
        else:
            thread = self.threads.create()
            
        thread_id = thread.id
        print(f"thread_id: {thread_id}")
        # thread_idをテキストファイルに保存
        with open('../logging/thread_ids.txt', 'a') as f:
            f.write(f"{thread_id}\n")
        return thread_id

    def retrieve_thread(self, thread_id: str):
        thread = self.threads.retrieve(thread_id)
        return thread

# Messageのモデルと変換関数
class MessageModel(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    annotations: list[str] | None = None
    file_ids: list[str] | None = None
    metadata: dict | None = None

def extract_message_model(message:ThreadMessage):
    JST = timezone(timedelta(hours=+9), 'JST')
    created_at_jst = datetime.fromtimestamp(message.created_at).astimezone(JST)

    message_model = MessageModel(
        id=message.id,
        role=message.role,
        content=message.content[0].text.value,
        created_at=created_at_jst,
        annotation=message.content[0].text.annotations or None,
        file_ids=message.file_ids or None,
        metadata=message.metadata or None,
    )
    return message_model


# create and run は、threadの新規作成を同時に行う。
class RunManager:
    def __init__(self, client: OpenAI, thread_id: str, assistant_id: str):
        self.client = client
        self.thread_id = thread_id
        self.assistant_id = assistant_id
        self.messages = client.beta.threads.messages
        self.runs = client.beta.threads.runs
        self.run_id = None  # Activeなrunのid
        self.run_status = None  # latest runのstatus
        # Execute only at instance creation
        self.details = self.get_messages()

    # Messages
    def create_message(self, content: str, role: str = "user", **kwargs):
        message = self.messages.create(
            thread_id=self.thread_id,
            role=role,
            content=content,    # content of message
            **kwargs
        )
        print(f"message_id: {message.id}")
        return message.id

    def get_messages(self, **kwargs):
        messages = self.messages.list(thread_id=self.thread_id, **kwargs)
        messages = [extract_message_model(message) for message in messages.data]
        self.details = messages 
        return messages
    
    def get_latest_message(self):
        messages = self.messages.list(thread_id=self.thread_id)
        message = messages.data[0]
        message_model = extract_message_model(message)
        return message_model

    def retrieve_message(self, message_id: str):
        message = self.messages.retrieve(thread_id=self.thread_id, message_id=message_id)
        # Use the extract_message_model function to create the Pydantic model
        message_model = extract_message_model(message)
        return message_model


    # Runs
    # エラーとなったrunが詰まるなら、updateの実装を検討する。
    def create_run(self, **kwargs):
        run = self.runs.create(
            thread_id=self.thread_id,
            assistant_id=self.assistant_id,
            **kwargs,  # instructions : Override the default system message of the assistant
        )
        run_id = run.id
        print(f"run_id: {run_id}")
        self.run_id = run_id
        return run_id

    # runデータを取得する。instructions等が含まれる。実質、不要。
    def get_runs(self, **kwargs):
        runs = self.runs.list(thread_id=self.thread_id, **kwargs)
        return runs

    def cycle_retrieve_run(self):
        """run_idが存在する間、runのstatusを取得し続ける。run_statusがcompletedになったら、run_idを初期化して終了する。"""
        if self.run_id is not None:
            while True:
                run = self.runs.retrieve(thread_id=self.thread_id, run_id=self.run_id)
                self.run_status = run.status
                print(f"run_status: {self.run_status}")
                # run_idを初期化して終了する。
                if self.run_status in ["completed", 'expired', "failed", "timed_out"]:
                    self.run_id = None
                    # Retrieve the latest message when the run is completed
                    latest_message = self.retrieve_message(self.get_latest_message().id)
                    print(f"Latest message: {latest_message}")
                    break
                time.sleep(2)  # Check status every 2 seconds
        else:
            print("No active run to retrieve status from.")
        return 


assistant_mgr = AssistantManager(client)
assistant_id = assistant_mgr.details[0]["id"]
thread_mgr = ThreadManager(client)
# thread = thread_mgr.create_thread()
thread_id = "thread_uCoQKyK11SZ0kH4fHPQ4pMJu"
thread = thread_mgr.retrieve_thread(thread_id)
print(thread)

run_mgr = RunManager(client, thread_id, assistant_id)

run_mgr.create_message("これはテストです。何回目の会話ですか？")
run_mgr.create_run()
run_mgr.cycle_retrieve_run()
