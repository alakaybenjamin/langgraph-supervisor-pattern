from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    action: Literal["send", "resume"] = "send"
    message: str = ""
    resume_data: dict = Field(default_factory=dict)
    thread_id: str = Field(default="")
    user_id: str = Field(default="anonymous")


class InterruptPayload(BaseModel):
    type: str = "interrupt"
    interrupt_value: dict
    thread_id: str


class ChatResponse(BaseModel):
    type: str
    content: str = ""
    thread_id: str = ""
    interrupt: InterruptPayload | None = None
