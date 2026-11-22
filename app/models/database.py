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

    def find_source(self, title: str) -> dict[str, Any] | None:
        rows = self.client.table("sources").select("*").eq("title", title).execute().data
        if len(rows) > 1:
            raise ValueError(f"{len(rows)} sources share the title {title!r}")
        return rows[0] if rows else None

    def insert_source(
        self,
        title: str,
        issuer: str,
        level: str,
        authority_rank: int,
        scopes: list[str],
        address: str | None,
        listing_address: str | None,
    ) -> dict[str, Any]:
        source = self.client.table("sources").insert({
            "title": title,
            "issuer": issuer,
            "level": level,
            "authority_rank": authority_rank,
            "address": address,
            "listing_address": listing_address,
        }).execute().data[0]
        if scopes:
            self.client.table("source_scopes").insert(
                [{"source_id": source["id"], "scope": s} for s in scopes]
            ).execute()
        return source

    def get_scopes(self, source_id: str) -> list[str]:
        rows = self.client.table("source_scopes").select("scope").eq("source_id", str(source_id)).execute().data
        return sorted(row["scope"] for row in rows)

    def update_source(self, source_id: str, fields: dict[str, Any]) -> None:
        self.client.table("sources").update(fields).eq("id", str(source_id)).execute()

    def set_scopes(self, source_id: str, scopes: list[str]) -> None:
        """Replace the source's scope rows with scopes."""
        self.client.table("source_scopes").delete().eq("source_id", str(source_id)).execute()
        if scopes:
            self.client.table("source_scopes").insert(
                [{"source_id": str(source_id), "scope": s} for s in scopes]
            ).execute()

    def get_known_scopes(self) -> list[str]:
        rows = self.client.table("source_scopes").select("scope").execute().data
        return list({row["scope"] for row in rows})

    # --- versions -----------------------------------------------------------

    def list_versions(self, source_id: str | None = None) -> list[dict[str, Any]]:
        """All versions, or those of one source."""
        query = self.client.table("versions").select("*")
        if source_id is not None:
            query = query.eq("source_id", str(source_id))
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
        source_id: str,
        title: str,
        address: str | None,
        file_path: str | None,
        file_sha256: str,
        kind: str = "new_version",
    ) -> dict[str, Any]:
        """Insert the flag that holds a new version, then the pending version itself."""
        flag = self.client.table("flags").insert(
            {"source_id": str(source_id), "kind": kind}
        ).execute().data[0]
        return self.client.table("versions").insert({
            "source_id": str(source_id),
            "status": "pending",
            "flag_id": flag["id"],
            "title": title,
            "address": address,
            "file_path": file_path,
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
