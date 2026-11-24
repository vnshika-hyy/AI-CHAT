from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: str | None = Field(default=None, max_length=4000)

    @field_validator("session_id")
    @classmethod
    def session_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("session_id must not be blank")
        return v


class ChatMetadata(BaseModel):
    resolution_source: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata
