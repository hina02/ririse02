from fastapi import APIRouter, UploadFile, File, Depends, Form
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
    instructions: str = Form(...),
    retrieval: bool = Form(False),
    code_interpreter: bool = Form(False),
    function: str = Form(None),
    uploaded_files: list[UploadFile] = File(None),
    client: OpenAI = Depends(get_openai_client),
):
    tools, file_ids = await generate_tools_and_files(
        retrieval, code_interpreter, function, uploaded_files, client
    )

    data = {
        "name": name,
        "description": description,
        "instructions": instructions,
    }
    if tools:
        data["tools"] = tools
    if file_ids:
        data["file_ids"] = file_ids

    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.create_assistant(**data)
    return assistant


# fileはfile_idsで返ってくるため、get_filesと照らし合わせる必要がある。
@assistant_router.get("/get_assistants", tags=["assistants"])
async def get_assistants(client: OpenAI = Depends(get_openai_client)):
    assistant_manager = AssistantManager(client)
    assistants = assistant_manager.get_assistants()
    return assistants


@assistant_router.post("/update_assistant/{asst_id}", tags=["assistants"])
async def update_assistant(
    asst_id: str,
    instructions: str = Form(None),
    retrieval: bool = Form(False),
    code_interpreter: bool = Form(False),
    function: str = Form(None),
    uploaded_files: list[UploadFile] = File(None),
    client: OpenAI = Depends(get_openai_client),
):
    tools, file_ids = await generate_tools_and_files(
        retrieval, code_interpreter, function, uploaded_files, client
    )

    data = {
        "asst_id": asst_id,
        "instructions": instructions,
    }
    if tools:
        data["tools"] = tools
    if file_ids:
        data["file_ids"] = file_ids

    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.update_assistant(**data)
    return assistant


@assistant_router.delete("/delete_assistant/{asst_id}", tags=["assistants"])
async def delete_assistant(asst_id: str, client: OpenAI = Depends(get_openai_client)):
    assistant_manager = AssistantManager(client)
    assistant_manager.delete_assistant(asst_id=asst_id)


# Threadの作成、取得
# 別途、Thread idの保存方法を検討し、クラスに渡す。
@assistant_router.post("/create_thread/{asst_id}", tags=["threads"])
async def create_thread(
    metadata: dict | None = None,
    client: OpenAI = Depends(get_openai_client),
):
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
