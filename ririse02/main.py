# ロガーをuvicornのロガーに設定する
import logging
from logging import getLogger

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ririse02 import config
from ririse02.assistant import assistant_router, file_router, run_router
from ririse02.chat.main import chat_router
from ririse02.chat.main.triplet import TripletsConverter
from ririse02.chat.neo4j import memory_router, neo4j_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(funcName)s]: %(message)s")
logger = getLogger(__name__)


app = FastAPI()
# OpenAI Assistant Routers
app.include_router(file_router, prefix="/assistant")
app.include_router(assistant_router, prefix="/assistant")
app.include_router(run_router, prefix="/assistant")
# Websocket Routers
app.include_router(chat_router)
app.include_router(neo4j_router, prefix="/chat")
app.include_router(memory_router, prefix="/chat")


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
