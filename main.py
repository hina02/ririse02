from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
import os
import binascii
import logging
from routers.openai_api import openai_api_router
from watchdog.observers import Observer
from watch_dog import MyHandler

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
