# 1. fileをリスト表示しておき、好きなタイミングで、アシスタント／メッセージに渡す。
# 2. アシスタント、メッセージ作成時に、ファイルのアップロードからまとめて行う。

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from openai import OpenAI
from openai.resources.files import FileObject
import os
import logging
from tempfile import NamedTemporaryFile
from routers.openai_api import get_openai_client

file_router = APIRouter()


# アップロード時に、一時ファイルを作成し、元のファイルの名前を付与する。
def create_temp_file(data, filename):
    temp_file = NamedTemporaryFile(delete=False)
    temp_file.write(data)
    temp_file.close()
    os.rename(temp_file.name, filename)
    return filename


# update
@file_router.post("/upload_file/", tags=["files"])
async def upload_file(
    file: UploadFile = File(...), client: OpenAI = Depends(get_openai_client)
) -> str:
    try:
        # 名前を指定するため、一時ファイルを作成し、アップロードされたファイルの内容を書き込む。
        data = await file.read()
        temp_file_name = create_temp_file(data, file.filename)

        # 一時ファイルを読み込み、その内容をOpenAIに渡す
        with open(temp_file_name, "rb") as f:
            response = client.files.create(file=f, purpose="assistants")

        # 一時ファイルを削除
        os.unlink(temp_file_name)
        response = response.model_dump()
        logging.info(response)
        return response.get("id")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")


@file_router.get("/get_files/", tags=["files"])
async def get_files(client: OpenAI = Depends(get_openai_client)) -> list[FileObject]:
    """files.data[0]で一つのfileObjectが取得できる"""
    files = client.files.list(purpose="assistants")
    return files


@file_router.get("/get_file/{file_id}", tags=["files"])
async def get_file(
    file_id: str, client: OpenAI = Depends(get_openai_client)
) -> FileObject:
    file = client.files.retrieve(file_id)
    return file


@file_router.delete("/delete_file/{file_id}", tags=["files"])
async def delete_file(file_id: str, client: OpenAI = Depends(get_openai_client)):
    response = client.files.delete(file_id)
    logging.info(response.model_dump())
    return
