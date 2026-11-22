from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from supabase import create_client


class DatabaseClient:
    def __init__(self, client=None):
        if client is None:
            settings = get_settings()
            self.client = create_client(settings.supabase_url, settings.supabase_service_key)
        else:
            self.client = client

    # --- sources ------------------------------------------------------------

    def find_source(self, key: str) -> dict[str, Any] | None:
        """The stored source with its level and sorted scope keys, or None."""
        rows = (
            self.client.table("sources").select("key, level, watch_address, source_scopes(scope_key)")
            .eq("key", key).execute().data
        )
        if not rows:
            return None
        row = rows[0]
        return {"key": row["key"], "level": row["level"], "watch_address": row["watch_address"],
                "scopes": sorted(s["scope_key"] for s in row.get("source_scopes") or [])}

    def save_source(self, key: str, level: str, scopes: list[str], watch_address: str | None) -> None:
        """Insert or update a source and replace its scopes, in one transaction.

        A new source, or a new watch address, stamps the source's confirmation date.
        """
        self.client.rpc("save_source", {
            "p_key": key, "p_level": level, "p_scopes": list(scopes),
            "p_watch_address": watch_address,
        }).execute()

    def list_source_keys(self) -> list[str]:
        rows = self.client.table("sources").select("key").execute().data
        return sorted(row["key"] for row in rows)

    def get_known_scopes(self) -> list[str]:
        """Keys of all defined scopes."""
        rows = self.client.table("scopes").select("key").execute().data
        return [row["key"] for row in rows]

    # --- versions -----------------------------------------------------------

    def list_versions(self, source_key: str | None = None) -> list[dict[str, Any]]:
        """All versions, or those of one source."""
        query = self.client.table("versions").select("*")
        if source_key is not None:
            query = query.eq("source_key", source_key)
        return query.execute().data

    def get_version(self, doc_id: uuid.UUID) -> dict[str, Any] | None:
        result = self.client.table("versions").select("*").eq("id", str(doc_id)).execute()
        return result.data[0] if result.data else None

    def update_version(self, doc_id: uuid.UUID, updates: dict[str, Any]) -> dict[str, Any]:
        return (
            self.client.table("versions")
            .update(updates)
            .eq("id", str(doc_id))
            .execute()
            .data[0]
        )

    def hold_version(
        self,
        source_key: str,
        title: str,
        version_label: str | None,
        obtained_from: str | None,
        page_limit: int | None,
        file_sha256: str,
        kind: str = "new_version",
    ) -> dict[str, Any]:
        """Insert the flag that holds a new version, then the pending version itself."""
        flag = self.client.table("flags").insert(
            {"source_key": source_key, "kind": kind}
        ).execute().data[0]
        return self.client.table("versions").insert({
            "source_key": source_key,
            "status": "pending",
            "flag_id": flag["id"],
            "title": title,
            "version_label": version_label,
            "obtained_from": obtained_from,
            "page_limit": page_limit,
            "file_sha256": file_sha256,
            "ingestion_status": "pending",
        }).execute().data[0]

    def set_text_fingerprint(self, doc_id: str, text_sha256: str, parsed_output: dict[str, Any]) -> None:
        self.client.table("versions").update(
            {"text_sha256": text_sha256, "parsed_output": parsed_output}
        ).eq("id", str(doc_id)).execute()

    def promote_version(self, doc_id: str | uuid.UUID, resolution: str) -> None:
        self.client.rpc(
            "promote_version", {"p_version_id": str(doc_id), "p_resolution": resolution}
        ).execute()

    def reject_version(self, doc_id: str | uuid.UUID, resolution: str) -> None:
        self.client.rpc(
            "reject_version", {"p_version_id": str(doc_id), "p_resolution": resolution}
        ).execute()

    def delete_pending_version(self, doc_id: str | uuid.UUID, resolution: str) -> None:
        """Remove a pending version that will not be kept (repackaging, interrupted load)."""
        doc = self.get_version(doc_id)
        if doc is None or doc.get("status") != "pending":
            raise ValueError(f"document {doc_id} is not pending")
        self.client.table("chunks").delete().eq("version_id", str(doc_id)).execute()
        self.client.table("versions").delete().eq("id", str(doc_id)).execute()
        self.client.table("flags").update({
            "resolved_at": datetime.now(UTC).isoformat(),
            "resolution": resolution,
        }).eq("id", doc["flag_id"]).execute()

    # --- chunks and search --------------------------------------------------

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        self.client.table("chunks").insert(chunks).execute()

    def vector_search(self, query_embedding: list[float], top_k: int = 20) -> list[dict[str, Any]]:
        return self.client.rpc(
            "match_chunks",
            {"query_embedding": query_embedding, "match_count": top_k},
        ).execute().data

    # --- answers ------------------------------------------------------------

    def log_answer(self, answer: dict[str, Any], version_ids: list[str]) -> str:
        """Store an answer and the versions it saw, in one transaction. Returns the answer id."""
        return self.client.rpc(
            "log_answer", {"p_answer": answer, "p_version_ids": list(version_ids)}
        ).execute().data

    def get_answer(self, answer_id: uuid.UUID) -> dict[str, Any] | None:
        result = self.client.table("answers").select("*").eq("id", str(answer_id)).execute()
        return result.data[0] if result.data else None

    # --- evaluation ---------------------------------------------------------

    def get_eval_questions(self) -> list[dict[str, Any]]:
        return self.client.table("eval_questions").select("*").execute().data

    def insert_eval_run(self, run_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.table("eval_runs").insert(run_data).execute().data[0]

    def list_eval_runs(self) -> list[dict[str, Any]]:
        return self.client.table("eval_runs").select("*").execute().data
