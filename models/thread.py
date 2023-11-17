from pydantic import BaseModel, validator
import json


# Thread, Assistantのmetatdataのモデルと変換関数
class MetadataModel(BaseModel):
    name: str
    description: str
    tags: str | list[str] | None = None

    @validator('tags', pre=True)
    def convert_tags(cls, v):
        # list[str] -> str  opneaiのmetadataはstrのみサポート
        if isinstance(v, list):
            return json.dumps(v)
        # str -> list[str]
        elif isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v


class ThreadModel(BaseModel):
    thread_id: str
    created_at: int  # Unix timestamp (in seconds)
    metadata: MetadataModel


# Messageのモデルと変換関数
class MessageModel(BaseModel):
    id: str
    role: str
    assistant_id: str | None = None
    content: str
    created_at: int  # Unix timestamp (in seconds)
    annotations: list[str] | None = None
    file_ids: list[str] | None = None
    metadata: dict | None = None
