from fastapi import APIRouter, UploadFile, File, Depends, Form, Body
from typing import Literal
import json
from openai import OpenAI
from openai_api.assistant import AssistantManager, ThreadManager
from routers.file import upload_files
from routers.openai_api import get_openai_client
from models.thread import MetadataModel, ThreadModel

assistant_router = APIRouter()


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


# Assistantの作成、更新、削除
@assistant_router.post("/create_assistant", tags=["assistants"])
async def create_assistant(
    name: str = Form(...),
    description: str = Form(...),
    model: Literal["gpt-4-1106-preview", "gpt-3.5-turbo-1106", "gpt-3.5-turbo-16k"] = Form(...),
    instructions: str = Form(...),
    retrieval: bool = Form(False),
    code_interpreter: bool = Form(False),
    function: str = Form(None),
    uploaded_files: list[UploadFile] = File(None),
    metadata: str = Form(None),
    client: OpenAI = Depends(get_openai_client),
):
    """metadata = {"tags": []} 16keyまで"""
    tools, file_ids = await generate_tools_and_files(retrieval, code_interpreter, function, uploaded_files, client)

    if metadata is not None:
        metadata = json.loads(metadata)
    data = {
        "name": name,
        "description": description,
        "model": model,
        "instructions": instructions,
    }
    if metadata is not None:
        data["metadata"] = metadata
    if tools:
        data["tools"] = tools
    if file_ids:
        data["file_ids"] = file_ids

    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.create_assistant(**data)
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
    return assistant


@assistant_router.post("/update_assistant/{assistant_id}", tags=["assistants"])
async def update_assistant(
    assistant_id: str,
    name: str = Form(None),
    description: str = Form(None),
    model: Literal["gpt-4-1106-preview", "gpt-3.5-turbo-1106", "gpt-3.5-turbo-16k"] = Form(None),
    instructions: str = Form(None),
    retrieval: bool = Form(False),
    code_interpreter: bool = Form(False),
    function: str = Form(None),
    uploaded_files: list[UploadFile] = File(None),
    metadata: str = Form(None),
    client: OpenAI = Depends(get_openai_client),
):
    tools, file_ids = await generate_tools_and_files(retrieval, code_interpreter, function, uploaded_files, client)

    if metadata is not None:
        metadata = json.loads(metadata)
    data = {
        "assistant_id": assistant_id,
    }
    if name is not None:
        data["name"] = name
    if description is not None:
        data["description"] = description
    if model is not None:
        data["model"] = model
    if instructions is not None:
        data["instructions"] = instructions
    if metadata is not None:
        data["metadata"] = metadata
    if tools:
        data["tools"] = tools
    if file_ids:
        data["file_ids"] = file_ids

    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.update_assistant(**data)
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
