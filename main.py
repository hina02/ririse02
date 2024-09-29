import binascii

# ロガーをuvicornのロガーに設定する
import logging
import os
from logging import getLogger

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware

import config
from assistant.routers.assistant import assistant_router
from assistant.routers.file import file_router
from assistant.routers.run import run_router
from chat_wb.neo4j.triplet import TripletsConverter
from chat_wb.routers.memory import memory_router
from chat_wb.routers.neo4j import neo4j_router
from chat_wb.routers.websocket import wb_router
from openai_api.routers import openai_api_router

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(funcName)s]: %(message)s"
)
logger = getLogger(__name__)
# wacthdogを用いたフォルダ監視のための設定
observer = None  # グローバル変数でObserverインスタンスを管理
development_flag = True  # 開発中はこのフラグをTrueに設定


app = FastAPI()
# OpenAI Assistant Routers
app.include_router(openai_api_router, prefix="/openai_api")
app.include_router(file_router, prefix="/openai_api")
app.include_router(assistant_router, prefix="/openai_api")
app.include_router(run_router, prefix="/openai_api")

# Websocket Routers
app.include_router(wb_router)
app.include_router(neo4j_router, prefix="/chat_wb")
app.include_router(memory_router, prefix="/chat_wb")

# CORSミドルウェアの追加
origins = [
    "http://127.0.0.1:4321",  # フロントエンドのオリジン
    "https://ririse-as.vercel.app",  # フロントエンドのオリジン
    "http://localhost:5173",
    "http://localhost:4322",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# セッションを有効にするための設定
secret_key = binascii.hexlify(os.urandom(24)).decode()
app.add_middleware(SessionMiddleware, secret_key=secret_key)


# /docsへのリンクを表示するために、HTMLResponseを返す
@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
    <html>
        <body>
            <p>Hello, World!</p>
            <a href="/docs">Go to docs</a>
        </body>
    </html>
    """


# test endpoint
@app.get("/run_sequences")
async def run_sequences_api(text: str):
    converter = TripletsConverter()
    await converter.triage_text(text)
    return await converter.run_sequences(text)
