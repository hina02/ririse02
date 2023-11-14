from fastapi import APIRouter, Depends, Request
import uuid
import logging
from openai import OpenAI
from openai_api.assistant import RunManager, MessageModel
from routers.openai_api import get_openai_client

run_router = APIRouter()

run_managers: dict = {}


def get_run_manager(
    request: Request, thread_id: str, assistant_id: str, client: OpenAI = Depends(get_openai_client)
) -> RunManager:
    if "user_id" not in request.session:
        request.session["user_id"] = str(uuid.uuid4())  # Generate a new user_id
    user_id = request.session["user_id"]

    if user_id not in run_managers:
        run_managers[user_id] = RunManager(
            client, thread_id=thread_id, assistant_id=assistant_id
        )
        logging.info(f"initialize user_id: {user_id}")
    return run_managers[user_id]


# messageの作成、Runの作成、Run結果の取得、メッセージ一覧の取得
@run_router.get("/create_message/{thread_id}/{assistant_id}", tags=["runs"])
def create_message(
    content: str,
    run_manager: RunManager = Depends(get_run_manager),
) -> str:
    message_id = run_manager.create_message(content=content)
    return message_id


@run_router.get("/get_messages/{thread_id}/{assistant_id}", tags=["runs"])
def get_messages(
    run_manager: RunManager = Depends(get_run_manager),
) -> list[MessageModel]:
    messages = run_manager.get_messages()
    return messages


@run_router.post("/create_run/{thread_id}/{assistant_id}", tags=["runs"])
def create_run(
    run_manager: RunManager = Depends(get_run_manager),
) -> str:
    run_id = run_manager.create_run()
    return run_id


# runを待機して、最新のメッセージを返す
@run_router.get("/get_run_result/{thread_id}/{assistant_id}", tags=["runs"])
def cycle_retrieve_run(
    run_manager: RunManager = Depends(get_run_manager),
) -> MessageModel | None:
    messages = run_manager.cycle_retrieve_run()
    return messages
