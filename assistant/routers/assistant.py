from fastapi import APIRouter, UploadFile, Depends, Body
import json
from openai import OpenAI
from assistant.assistant import AssistantManager, ThreadManager
from assistant.routers.file import upload_files
from assistant.assistant import get_openai_client
from assistant.models import MetadataModel, ThreadModel, AssistantModel
from logging import getLogger

logger = getLogger(__name__)

assistant_router = APIRouter()


def generate_tools(
    retrieval: bool,
    code_interpreter: bool,
    function: dict,
):
    tools = []
    if retrieval:
        tools.append({"type": "retrieval"})
    if code_interpreter:
        tools.append({"type": "code_interpreter"})
    if function:
        tools.append({"type": "function", "function": function})
    return tools


async def generate_tools_and_files(
    retrieval: bool,
    code_interpreter: bool,
    function: dict,
    uploaded_files: list[UploadFile],
    client: OpenAI,
):
    tools = []
    if retrieval:
        tools.append({"type": "retrieval"})
    if code_interpreter:
        tools.append({"type": "code_interpreter"})
    if function:
        tools.append({"type": "function", "function": function})

    if uploaded_files and (retrieval | code_interpreter):
        file_ids = await upload_files(uploaded_files, client)
    else:
        file_ids = None

    return tools, file_ids


def manage_assistant_data(data: AssistantModel, assistant_id: str = None):
    tools = generate_tools(data.retrieval, data.code_interpreter, data.function)

    _data = {
        "assistant_id": assistant_id if assistant_id else None,
        "name": data.name,
        "description": data.description,
        "model": data.model,
        "instructions": data.instructions,
        "metadata": {"tags": json.dumps(data.tags)} if data.tags else None,
        "tools": tools if tools else None,
        "file_ids": data.file_ids if data.file_ids else None,
    }

    # Noneの値を持つキーを削除
    _data = {k: v for k, v in _data.items() if v is not None}
    return _data


# Assistantの作成、更新、削除
@assistant_router.post("/create_assistant", tags=["assistants"])
async def create_assistant(
    data: AssistantModel,
    client: OpenAI = Depends(get_openai_client),
):
    """metadata = {"tags": []} 16keyまで"""
    _data = manage_assistant_data(data)

    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.create_assistant(**_data)
    logger.info(assistant)
    return assistant


# fileはfile_idsで返ってくるため、get_filesと照らし合わせる必要がある。
# id, name, descriptionだけを返す。
@assistant_router.get("/get_assistants", tags=["assistants"])
async def get_assistants(client: OpenAI = Depends(get_openai_client)):
    assistant_manager = AssistantManager(client)
    assistants = assistant_manager.get_assistants()

    assistants = [{"assistant_id": asst["id"], "name": asst["name"], "description": asst["description"]} for asst in assistants]
    return assistants


@assistant_router.get("/get_assistant/{assistant_id}", tags=["assistants"])
async def get_assistant(assistant_id: str, client: OpenAI = Depends(get_openai_client)):
    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.get_assistant_details(assistant_id=assistant_id)
    # metadata.tags -> tags
    if 'metadata' in assistant and 'tags' in assistant['metadata']:
        assistant['tags'] = json.loads(assistant['metadata']['tags'])
    del assistant['metadata']
    return assistant


@assistant_router.post("/update_assistant/{assistant_id}", tags=["assistants"])
async def update_assistant(
    assistant_id: str,
    data: AssistantModel,
    client: OpenAI = Depends(get_openai_client),
):
    _data = manage_assistant_data(data, assistant_id=assistant_id)

    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.update_assistant(**_data)
    return assistant


@assistant_router.delete("/delete_assistant/{assistant_id}", tags=["assistants"])
async def delete_assistant(assistant_id: str, client: OpenAI = Depends(get_openai_client)):
    assistant_manager = AssistantManager(client)
    assistant_manager.delete_assistant(assistant_id=assistant_id)


# Threadの作成、取得
# 別途、Thread idの保存方法を検討し、クラスに渡す。
@assistant_router.post("/create_thread", tags=["threads"])
async def create_thread(
    metadata: MetadataModel = Body(...),
    client: OpenAI = Depends(get_openai_client),
):
    """metadata = {"name" : name, "description" : description, "tags": []} 16keyまで"""
    thread_manager = ThreadManager(client)
    thread_id = thread_manager.create_thread(metadata=metadata)
    return thread_id


# logging\thread_models.jsonlに保存されたthreadを取得する
@assistant_router.get("/get_threads", tags=["threads"])
def get_threads():
    threads = []
    with open("logging/thread_models.jsonl", "r") as f:
        for line in f:
            thread_model = ThreadModel.model_validate_json(line.strip())
            # 新しい辞書を作成し、スレッドモデルのデータとメタデータを追加
            thread_dict = {**thread_model.model_dump(), **thread_model.metadata.model_dump()}
            thread_dict.pop("metadata")
            if "tags" in thread_dict and thread_dict["tags"] is not None:
                thread_dict["tags"] = json.loads(thread_dict["tags"])
            threads.append(thread_dict)
    return threads

@assistant_router.get("/get_thread/{thread_id}", tags=["threads"])
async def get_thread(
    thread_id: str,
    client: OpenAI = Depends(get_openai_client),
):
    thread_manager = ThreadManager(client)
    thread = thread_manager.retrieve_thread(thread_id=thread_id)
    return thread


# delete thread
@assistant_router.delete("/delete_thread/{thread_id}", tags=["threads"])
async def delete_thread(
    thread_id: str,
    client: OpenAI = Depends(get_openai_client),
):
    thread_manager = ThreadManager(client)
    thread_manager.delete_thread(thread_id=thread_id)
