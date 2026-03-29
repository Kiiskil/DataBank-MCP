"""JSON-skeemat vastauksille ja viitteille."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    chunk_id: str
    quote: str
    book: str = ""
    chapter: str = ""


class ZtAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)

    @field_validator("citations", mode="before")
    @classmethod
    def _citations_list(cls, v: Any) -> Any:
        if v is None:
            return []
        return v


REFUSAL_ANSWER = "Ei löydy lähteistäni."


def refusal_payload() -> dict[str, Any]:
    return {"answer": REFUSAL_ANSWER, "citations": []}
