from __future__ import annotations

import uuid
from typing import Any

from supabase import create_client

from app.config import get_settings


class DatabaseClient:
    def __init__(self, client=None):
        if client is None:
            settings = get_settings()
            self.client = create_client(settings.supabase_url, settings.supabase_service_key)
        else:
            self.client = client

    def list_documents(self) -> list[dict[str, Any]]:
        return self.client.table("documents").select("*").execute().data

    def get_document(self, doc_id: uuid.UUID) -> dict[str, Any] | None:
        result = (
            self.client.table("documents")
            .select("*")
            .eq("id", str(doc_id))
            .execute()
        )
        return result.data[0] if result.data else None

    def insert_document(
        self,
        title: str,
        doc_type: str,
        hierarchy_priority: int,
        file_path: str,
        grid_provider: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "title": title,
            "doc_type": doc_type,
            "hierarchy_priority": hierarchy_priority,
            "file_path": file_path,
            "ingestion_status": "pending",
        }
        if grid_provider:
            data["grid_provider"] = grid_provider
        return self.client.table("documents").insert(data).execute().data[0]

    def update_document(self, doc_id: uuid.UUID, updates: dict[str, Any]) -> dict[str, Any]:
        return (
            self.client.table("documents")
            .update(updates)
            .eq("id", str(doc_id))
            .execute()
            .data[0]
        )

    def delete_document(self, doc_id: uuid.UUID) -> None:
        self.client.table("documents").delete().eq("id", str(doc_id)).execute()

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        self.client.table("document_chunks").insert(chunks).execute()

    def delete_chunks_for_document(self, doc_id: uuid.UUID) -> None:
        self.client.table("document_chunks").delete().eq("document_id", str(doc_id)).execute()

    def vector_search(self, query_embedding: list[float], top_k: int = 20) -> list[dict[str, Any]]:
        return self.client.rpc(
            "match_document_chunks",
            {
                "query_embedding": query_embedding,
                "match_count": top_k,
            },
        ).execute().data

    def keyword_search(self, query: str, top_k: int = 20) -> list[dict[str, Any]]:
        return self.client.rpc(
            "keyword_search_chunks",
            {
                "search_query": query,
                "match_count": top_k,
            },
        ).execute().data

    def insert_query_log(self, log_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.table("query_logs").insert(log_data).execute().data[0]

    def get_query_log(self, log_id: uuid.UUID) -> dict[str, Any] | None:
        result = (
            self.client.table("query_logs")
            .select("*")
            .eq("id", str(log_id))
            .execute()
        )
        return result.data[0] if result.data else None

    def get_eval_questions(self) -> list[dict[str, Any]]:
        return self.client.table("eval_questions").select("*").execute().data

    def insert_eval_run(self, run_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.table("eval_runs").insert(run_data).execute().data[0]

    def list_eval_runs(self) -> list[dict[str, Any]]:
        return self.client.table("eval_runs").select("*").execute().data

    def get_known_providers(self) -> list[str]:
        result = (
            self.client.table("documents")
            .select("grid_provider")
            .not_.is_("grid_provider", "null")
            .execute()
        )
        return list({row["grid_provider"] for row in result.data})
