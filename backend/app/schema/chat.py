from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    thread_id: str = Field(default="")
    user_id: str = Field(default="anonymous")


class ChatResumeRequest(BaseModel):
    resume_data: dict
    thread_id: str
    user_id: str = Field(default="anonymous")


class InterruptPayload(BaseModel):
    type: str = "interrupt"
    interrupt_value: dict
    thread_id: str


class ChatResponse(BaseModel):
    type: str  # "message" | "interrupt" | "error"
    content: str = ""
    thread_id: str = ""
    interrupt: InterruptPayload | None = None
