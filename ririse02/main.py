import binascii

# ロガーをuvicornのロガーに設定する
import logging
import os
from contextlib import asynccontextmanager
from logging import getLogger

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from watchdog.observers import Observer

from ririse02 import config
from ririse02.assistant import assistant_router, file_router, run_router
from ririse02.chat.main import chat_router
from ririse02.chat.main.triplet import TripletsConverter
from ririse02.chat.neo4j import memory_router, neo4j_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(funcName)s]: %(message)s")
logger = getLogger(__name__)
# wacthdogを用いたフォルダ監視のための設定
observer = None  # グローバル変数でObserverインスタンスを管理
development_flag = True  # 開発中はこのフラグをTrueに設定


# watchdogの非同期監視設定。アプリケーション起動時にFastAPI lifespanで実行する。
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global observer
    if not development_flag:  # 開発中は監視を行わない
        from watch_dog import MyHandler

        folder_to_track = "folder"
        event_handler = MyHandler()
        observer = Observer()
        observer.schedule(event_handler, folder_to_track, recursive=True)
        observer.start()

    yield  # ここでアプリケーションがリクエストを処理します

    if observer is not None:
        observer.stop()
        observer.join()


app = FastAPI(lifespan=app_lifespan)
# OpenAI Assistant Routers
app.include_router(file_router, prefix="/assistant")
app.include_router(assistant_router, prefix="/assistant")
app.include_router(run_router, prefix="/assistant")
# Websocket Routers
app.include_router(chat_router)
app.include_router(neo4j_router, prefix="/chat")
app.include_router(memory_router, prefix="/chat")

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


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
