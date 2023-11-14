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
    if os.path.exists(filename):
        os.remove(filename)
    os.rename(temp_file.name, filename)
    return filename


@file_router.post("/upload_file/", tags=["files"])
async def upload_files(
    files: list[UploadFile] = File(...), client: OpenAI = Depends(get_openai_client)
) -> list[str]:
    file_ids = []
    try:
        for file in files:
            # ファイルサイズが512MBを超えていないことを確認
            if file.file._file.tell() > 512 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="File size exceeds limit")

            # 名前を指定するため、一時ファイルを作成し、アップロードされたファイルの内容を書き込む。
            data = await file.read()
            temp_file_name = create_temp_file(data, file.filename)

            try:
                # 一時ファイルを読み込み、その内容をOpenAIに渡す
                with open(temp_file_name, "rb") as f:
                    response = client.files.create(file=f, purpose="assistants")

                response = response.model_dump()
                logging.info(response)
                file_ids.append(response.get("id"))
            finally:
                os.unlink(temp_file_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    return file_ids


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
