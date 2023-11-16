from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import os
import binascii
import logging
from routers.openai_api import openai_api_router
from routers.file import file_router
from routers.assistant import assistant_router
from routers.run import run_router
from watchdog.observers import Observer

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(funcName)s]: %(message)s"
)


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
app.include_router(openai_api_router)
app.include_router(file_router)
app.include_router(assistant_router)
app.include_router(run_router)

# CORSミドルウェアの追加
origins = [
    "http://127.0.0.1:4321",  # フロントエンドのオリジン
    "http://localhost:4321",
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


# logging\thread_ids.txtに保存されたthread_idを取得する
@app.get("/get_thread_ids", tags=["threads"])
def get_thread_ids():
    thread_ids = []
    with open("logging/thread_ids.txt", "r") as f:
        for line in f:
            thread_ids.append(line.strip())
    return thread_ids
