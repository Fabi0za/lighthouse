from __future__ import annotations

from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str


class EvalRunRequest(BaseModel):
    notes: str | None = None
