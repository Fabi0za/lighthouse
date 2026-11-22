from __future__ import annotations

from pydantic import BaseModel


class DocumentUpdate(BaseModel):
    title: str | None = None


class QueryRequest(BaseModel):
    question: str


class EvalRunRequest(BaseModel):
    notes: str | None = None
