from fastapi import APIRouter, Depends, Request, Query, HTTPException
import uuid
import logging
from openai import OpenAI
from openai_api.assistant import RunManager, MessageModel
from routers.openai_api import get_openai_client

run_router = APIRouter()

run_managers: dict = {}


def get_run_manager(
    request: Request,
    thread_id: str,
    client: OpenAI = Depends(get_openai_client),
) -> RunManager:
    if "user_id" not in request.session:
        request.session["user_id"] = str(uuid.uuid4())  # Generate a new user_id
    user_id = request.session["user_id"]

    if user_id not in run_managers:
        run_managers[user_id] = RunManager(client, thread_id=thread_id)
        logging.info(f"initialize user_id: {user_id}")
    return run_managers[user_id]


# messageの作成、Runの作成、Run結果の取得、メッセージ一覧の取得
@run_router.post("/create_message/{thread_id}", tags=["runs"])
def create_message(
    content: str = Query(...),
    run_manager: RunManager = Depends(get_run_manager),
) -> str:
    message_id = run_manager.create_message(content=content)
    return message_id


# create_runでassistantを指定する
@run_router.post("/create_run/{thread_id}/{assistant_id}", tags=["runs"])
def create_run(
    assistant_id: str,
    run_manager: RunManager = Depends(get_run_manager),
) -> str:
    run_id = run_manager.create_run(assistant_id)
    return run_id


# create_messageとcreate_runを同時に行う
@run_router.post("/create_message_and_run/{thread_id}/{assistant_id}", tags=["runs"])
def create_message_and_run(
    assistant_id: str,
    content: str = Query(...),
    run_manager: RunManager = Depends(get_run_manager),
) -> str:
    try:
        run_manager.create_message(content=content)
        run_manager.create_run(assistant_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# runを待機して、最新のメッセージを返す
@run_router.get("/retrieve_run_result/{thread_id}}", tags=["runs"])
def retrieve_run_result(
    run_manager: RunManager = Depends(get_run_manager),
) -> MessageModel | None:
    messages = run_manager.cycle_retrieve_run()
    return messages


@run_router.get("/get_messages/{thread_id}", tags=["runs"])
def get_messages(
    run_manager: RunManager = Depends(get_run_manager),
) -> list[MessageModel]:
    messages = run_manager.get_messages()
    return messages
