import requests
from fastapi import Request
import uuid
from openai import OpenAI
from openai.types.beta.assistant import Assistant  # アシスタントの型
from openai.types.beta.thread import Thread  # スレッドの型
from openai.types.beta.threads import ThreadMessage  # メッセージの型
import os
import time
from logging import getLogger
import json
from assistant.models import MetadataModel, ThreadModel, MessageModel

logger = getLogger(__name__)

openai_api_key = os.getenv("OPENAI_API_KEY")

# Clients for assistant module
clients: dict = {}


def get_openai_client(request: Request) -> OpenAI:
    if "user_id" not in request.session:
        request.session["user_id"] = str(uuid.uuid4())  # Generate a new user_id
    user_id = request.session["user_id"]

    if user_id not in clients:
        clients[user_id] = OpenAI()  # defaults to os.environ.get("OPENAI_API_KEY")
        logger.info(f"initialize user_id: {user_id}")

    print(clients[user_id])
    return clients[user_id]

# client.beta.assistants.filesは、fileをassistatnsに紐付ける。


class AssistantManager:
    def __init__(self, client: OpenAI):
        self.client = client
        self.assistants = client.beta.assistants
        # openai apiリクエストのヘッダー
        self.__headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "OpenAI-Beta": "assistants=v1",
        }

    # get   # listの取得は、pagenationもあるので、フロントから直接が良さそう。
    def get_assistants_ids(self) -> list[str]:
        response = requests.get(
            "https://api.openai.com/v1/assistants?order=desc&limit=20",
            headers=self.__headers,
        )
        response_data = response.json()["data"]
        assistant_ids = [data["id"] for data in response_data]
        return assistant_ids

    def get_assistant_details(self, assistant_id: str) -> Assistant:
        response = requests.get(
            f"https://api.openai.com/v1/assistants/{assistant_id}", headers=self.__headers
        )
        return response.json()

    def get_assistants(self) -> list[Assistant]:
        response = requests.get(
            "https://api.openai.com/v1/assistants?order=desc&limit=20",
            headers=self.__headers,
        )
        try:
            response_data = response.json()["data"]
        except KeyError:
            logger.error(f"Key Error: {response.json()}")
            response_data = []
        return response_data

    # create
    def create_assistant(
        self,
        **kwargs,
    ) -> Assistant:
        assistant = self.assistants.create(**kwargs)
        return assistant

    # update
    def update_assistant(
        self,
        assistant_id: str,
        **kwargs,
    ) -> Assistant:
        data = {}
        data.update(kwargs)
        response = requests.post(
            f"https://api.openai.com/v1/assistants/{assistant_id}",
            headers=self.__headers,
            json=data,
        )
        return response.json()

    # delete
    def delete_assistant(self, assistant_id: str):
        response = requests.delete(
            f"https://api.openai.com/v1/assistants/{assistant_id}", headers=self.__headers
        )
        logger.info(response.json())
        return


# スレッドの作成
# Threadsは、Assistantとは独立。AssistantはRun時に指定する。
# 現時点では、messagesはrole:userのみサポート
# metadata(16までのkey value)に、追加情報を与えられるのが素晴らしい。
# retrieve, update, delete, create_and_runもサポート
class ThreadManager:
    def __init__(self, client: OpenAI):
        self.client = client

    def create_thread(self, metadata: MetadataModel) -> ThreadModel:
        thread = self.client.beta.threads.create(metadata=metadata)
        
        # スレッドモデルを作成して保存
        thread_model = ThreadModel(
            thread_id=thread.id,
            created_at=thread.created_at,
            metadata=thread.metadata,
        )
        logger.info(f"thread_model: {thread_model}")
        # スレッドモデルをJSON Lineファイルに保存
        with open("logging/thread_models.jsonl", "a") as f:
            f.write(json.dumps(thread_model.model_dump()) + "\n")
    
        return thread_model

    def retrieve_thread(self, thread_id: str) -> Thread:
        thread = self.client.beta.threads.retrieve(thread_id)
        return thread
    
    # thread_models.jsonlから、threadを削除する。
    def delete_thread(self, thread_id: str):
        with open("logging/thread_models.jsonl", "r") as f:
            lines = f.readlines()
        # ファイルを開き、thread_idが一致する行を取り除く。
        new_lines = []
        for line in lines:
            thread_model = ThreadModel.model_validate_json(line.strip())
            if thread_model.thread_id != thread_id:
                new_lines.append(line)
        # ファイルを上書きする
        with open("logging/thread_models.jsonl", "w") as f:
            for line in new_lines:
                f.write(line)


def extract_message_model(message: ThreadMessage):
    message_model = MessageModel(
        id=message.id,
        role=message.role,
        assistant_id=message.assistant_id or None,
        content=message.content[0].text.value,
        created_at=message.created_at,
        annotations=message.content[0].text.annotations or None,
        file_ids=message.file_ids or None,
        metadata=message.metadata or None,
    )
    return message_model


# create and run は、threadの新規作成を同時に行う。
class RunManager:
    def __init__(self, client: OpenAI, thread_id: str):
        self.client = client
        self.thread_id = thread_id
        self.run_id = None  # Activeなrunのid
        self.run_status = None  # latest runのstatus
        # Execute only at instance creation
        self.details = self.get_messages()

    # Messages
    def create_message(self, content: str, role: str = "user", **kwargs) -> str:
        message = self.client.beta.threads.messages.create(
            thread_id=self.thread_id,
            role=role,
            content=content,  # content of message
            **kwargs,
        )
        logger.info(f"message_id: {message.id}")
        return message.id

    def get_messages(self, **kwargs) -> list[MessageModel]:
        messages = self.client.beta.threads.messages.list(
            thread_id=self.thread_id, **kwargs
        )
        messages = [extract_message_model(message) for message in messages.data]
        self.details = messages
        return messages

    def get_latest_message(self) -> MessageModel:
        messages = self.client.beta.threads.messages.list(thread_id=self.thread_id)
        message = messages.data[0]
        message_model = extract_message_model(message)
        return message_model

    def retrieve_message(self, message_id: str) -> MessageModel:
        message = self.client.beta.threads.messages.retrieve(
            thread_id=self.thread_id, message_id=message_id
        )
        # Use the extract_message_model function to create the Pydantic model
        message_model = extract_message_model(message)
        return message_model

    # Runs
    # エラーとなったrunが詰まるなら、update, cancel, submit_tool_outputsの実装を検討する。
    # 1回のRunで、複数のメッセージを処理できる。複数のRunは同時に実行できない。
    def create_run(self, assistant_id: str, **kwargs) -> str:
        run = self.client.beta.threads.runs.create(
            thread_id=self.thread_id,
            assistant_id=assistant_id,
            **kwargs,  # instructions : Override the default system message of the assistant
        )
        run_id = run.id
        logger.info(f"run_id: {run_id}")
        self.run_id = run_id
        return run_id

    # runデータを取得する。instructions等が含まれる。実質、不要。
    def get_runs(self, **kwargs):
        runs = self.client.beta.threads.runs.list(thread_id=self.thread_id, **kwargs)
        return runs

    def cycle_retrieve_run(self) -> str:
        """run_idが存在する間、runのstatusを取得し続ける。run_statusがcompletedになったら、run_idを初期化して終了する。"""
        if self.run_id is not None:
            while True:
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=self.thread_id, run_id=self.run_id
                )
                self.run_status = run.status
                logger.info(f"run_status: {self.run_status}")
                # run_idを初期化して終了する。
                if self.run_status in ["completed", "expired", "failed", "timed_out"]:
                    self.run_id = None
                    # # Retrieve the latest message when the run is completed
                    # latest_message = self.retrieve_message(self.get_latest_message().id)
                    # logger.info(f"Latest message: {latest_message}")
                    break
                time.sleep(2)  # Check status every 2 seconds
        else:
            logger.info("No active run to retrieve status from.")
            return "empty"
        return self.run_status


# thread_mgr = ThreadManager(client)
# # thread = thread_mgr.create_thread()
# thread_id = "thread_uCoQKyK11SZ0kH4fHPQ4pMJu"
# thread = thread_mgr.retrieve_thread(thread_id)
# print(thread)

# run_mgr = RunManager(client, thread_id)

# run_mgr.create_message("これは何時の質問ですか？")
# run_mgr.create_message("これは何回目の質問ですか？")
# run_mgr.create_run(assistant_id="asst_lpqx1KFftad7N2NKxjDLd8tw")
# run_mgr.cycle_retrieve_run()
