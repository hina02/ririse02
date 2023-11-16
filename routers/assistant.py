from fastapi import APIRouter, UploadFile, File, Depends, Form
from typing import Literal
import json
from openai import OpenAI
from openai_api.assistant import AssistantManager, ThreadManager
from routers.file import upload_files
from routers.openai_api import get_openai_client

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
    tools, file_ids = await generate_tools_and_files(
        retrieval, code_interpreter, function, uploaded_files, client
    )

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
    tools, file_ids = await generate_tools_and_files(
        retrieval, code_interpreter, function, uploaded_files, client
    )

    if metadata is not None:
        metadata = json.loads(metadata)
    data = {
        "assistant_id": assistant_id,
    }
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
@assistant_router.post("/create_thread/{assistant_id}", tags=["threads"])
async def create_thread(
    metadata: dict | None = None,
    client: OpenAI = Depends(get_openai_client),
):
    """metadata = {"title" : title, "description" : description} 16keyまで"""
    thread_manager = ThreadManager(client)
    thread_id = thread_manager.create_thread(metadata=metadata)
    return thread_id


@assistant_router.get("/get_thread/{thread_id}", tags=["threads"])
async def get_thread(
    thread_id: str,
    client: OpenAI = Depends(get_openai_client),
):
    thread_manager = ThreadManager(client)
    thread = thread_manager.retrieve_thread(thread_id=thread_id)
    return thread
