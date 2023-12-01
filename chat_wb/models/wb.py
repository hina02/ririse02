from pydantic import BaseModel


# WebScoketで受け取るデータのモデル
class WebSocketInputData(BaseModel):
    source: str     # user_id or assistant_id(asst_) # user_id作成時にasst_の使用を禁止する
    input_text: str
    title: str | None = None
    former_node_id: int | None = None   # node_idを渡すことで、途中のメッセージに新しいメッセージを追加することができる。
                                        # 使用する場合、フロントで枝分かれの表示方法の実装が必要。
