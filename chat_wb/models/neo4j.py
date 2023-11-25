import logging
from typing import Literal

from pydantic import BaseModel, field_validator

# ロガー設定
logger = logging.getLogger(__name__)


class Node(BaseModel):
    id: int | None
    label: Literal[
        "Person",
        "Organization",
        "Consume",
        "Equipment",
        "Object",
        "Spot",
        "Location",
        "Planet",
        "Galaxy",
    ] | None
    name: str | None
    properties: dict | None

    # Activityは、プロパティ要素
    @field_validator("label", mode="before")
    def check_type(cls, value):
        """validate label"""
        if value not in [
            "Person",
            "Organization",
            "Consume",
            "Equipment",
            "Object",
            "Spot",
            "Location",
            "Planet",
            "Galaxy",
        ]:
            return None
        return value


class Relation(BaseModel):
    id: int | None
    type: Literal[
        "Located_at", "Has", "Equip", "Belong_to", "Related_to", "Act_on"
    ] | None
    content: list[str] | None
    time: str | None
    node1: str | None  # node1, node2の名前を入れる
    node2: str | None

    @field_validator("type", mode="before")
    def check_type(cls, value):
        if value not in [
            "Located_at",
            "Has",
            "Equip",
            "Belong_to",
            "Related_to",
            "Act_on",
        ]:
            return None
        return value
