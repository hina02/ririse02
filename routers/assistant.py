from fastapi import APIRouter, UploadFile, File, Depends, Body, HTTPException
from openai import OpenAI
from openai_api.assistant import AssistantManager, ThreadManager
from openai.types.beta.assistant_create_params import ToolAssistantToolsFunctionFunction
from routers.file import upload_files
from routers.openai_api import get_openai_client
import json


assistant_router = APIRouter()


def validate_function(function: dict | None):
    if function is not None:
        if not isinstance(function, ToolAssistantToolsFunctionFunction):
            raise HTTPException(
                status_code=400,
                detail="The 'function' key must be followed ToolAssistantToolsFunctionFunction",
            )
    return function


def validate_tools(tools: str | None):
    try:
        tools = json.loads(tools) if tools else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format in tools")

    valid_types = ["code_interpreter", "retrieval", "function"]
    if tools is not None:
        for tool in tools:
            if not isinstance(tool, dict):
                raise HTTPException(
                    status_code=400, detail="Each tool must be a dictionary"
                )
            if tool.get("type") not in valid_types:
                raise HTTPException(
                    status_code=400, detail=f"Invalid tool type: {tool.get('type')}"
                )
            if tool.get("type") == "function":
                validate_function(tool.get("function"))
    return tools


# Assistantの作成、更新、削除
@assistant_router.post("/create_assistant", tags=["assistants"])
async def create_assistant(
    name: str,
    description: str,
    instructions: str,
    tools: str = Body(None),
    uploaded_files: list[UploadFile] = File(None),
    client: OpenAI = Depends(get_openai_client),
):
    tools = validate_tools(tools)
    if upload_files and any(
        tool["type"] in ["code_interpreter", "retrieval"] for tool in tools
    ):
        file_ids = await upload_files(uploaded_files, client)
    else:
        file_ids = None

    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.create_assistant(
        name=name,
        description=description,
        instructions=instructions,
        tools=tools,
        file_ids=file_ids,
    )
    return assistant


@assistant_router.get("/get_assistants", tags=["assistants"])
async def get_assistants(client: OpenAI = Depends(get_openai_client)):
    assistant_manager = AssistantManager(client)
    assistants = assistant_manager.get_assistants()
    return assistants


@assistant_router.post("/update_assistant/{asst_id}", tags=["assistants"])
async def update_assistant(
    asst_id: str,
    instructions: str,
    tools: str = Body(None),
    uploaded_files: list[UploadFile] = File(None),
    client: OpenAI = Depends(get_openai_client),
):
    tools = validate_tools(tools)
    if upload_files and any(
        tool["type"] in ["code_interpreter", "retrieval"] for tool in tools
    ):
        file_ids = await upload_files(uploaded_files, client)
    else:
        file_ids = None

    assistant_manager = AssistantManager(client)
    assistant = assistant_manager.update_assistant(
        asst_id=asst_id, instructions=instructions, tools=tools, file_ids=file_ids
    )
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
