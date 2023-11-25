from pydantic import BaseModel


# WebScoketで受け取るデータのモデル
class WebSocketInputData(BaseModel):
    input_text: str
    title: str | None = None
    former_node_id: int | None = None   # 消す
