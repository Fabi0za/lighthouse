from __future__ import annotations

import uuid
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

    def save_indexing_settings(self, row: dict[str, Any]) -> None:
        self.client.table("indexing_settings").upsert(row, on_conflict="key").execute()

    def save_answer_settings(self, row: dict[str, Any]) -> None:
        self.client.table("answer_settings").upsert(row, on_conflict="key").execute()

    def current_indexing_settings_keys(self) -> list[str]:
        """The indexing settings that current versions were loaded with (one, unless empty)."""
        rows = (
            self.client.table("versions").select("indexing_settings_key")
            .eq("status", "current").execute().data
        )
        return sorted({row["indexing_settings_key"] for row in rows})

    def save_levels(self, rows: list[dict[str, Any]]) -> None:
        """Insert or update levels (key, rank, requires_scope)."""
        self.client.table("levels").upsert(rows, on_conflict="key").execute()

    def save_scopes(self, rows: list[dict[str, Any]]) -> None:
        """Insert or update scopes (key, name)."""
        self.client.table("scopes").upsert(rows, on_conflict="key").execute()

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

    def find_version(self, source_key: str, version_label: str) -> dict[str, Any] | None:
        rows = (
            self.client.table("versions").select("*")
            .eq("source_key", source_key).eq("version_label", version_label).execute().data
        )
        return rows[0] if rows else None

    def begin_load(
        self,
        source_key: str,
        title: str,
        version_label: str | None,
        obtained_from: str | None,
        page_limit: int | None,
        file_sha256: str,
        indexing_settings_key: str,
    ) -> str:
        """Start loading a file as a version (status loading, no flag); returns the version id.

        A loading or failed version with the same bytes is taken up again.
        """
        return self.client.rpc("begin_load", {
            "p_source_key": source_key, "p_title": title, "p_version_label": version_label,
            "p_obtained_from": obtained_from, "p_page_limit": page_limit, "p_file_sha256": file_sha256,
            "p_indexing_settings_key": indexing_settings_key,
        }).execute().data

    def set_text_fingerprint(self, version_id: str, text_sha256: str, parsed_output: dict[str, Any]) -> None:
        self.client.table("versions").update(
            {"text_sha256": text_sha256, "parsed_output": parsed_output}
        ).eq("id", str(version_id)).execute()

    def fail_load(self, version_id: str, reason: str, file: str, message: str) -> int:
        """Mark the load failed and flag it (parse_failed or load_failed); returns the flag number."""
        return self.client.rpc("fail_load", {
            "p_version_id": str(version_id), "p_reason": reason, "p_file": file, "p_message": message,
        }).execute().data

    def discard_version(self, version_id: str) -> None:
        """Delete a loading or failed version that will not be kept."""
        self.client.rpc("discard_version", {"p_version_id": str(version_id)}).execute()

    def promote_version(self, version_id: str, resolved_by: str = "system") -> int:
        """Make the version current; returns how many earlier answers saw the version it retired."""
        return self.client.rpc(
            "promote_version", {"p_version_id": str(version_id), "p_resolved_by": resolved_by}
        ).execute().data

    def reject_version(self, version_id: str) -> None:
        """A person rejects a held candidate."""
        self.client.rpc("reject_version", {"p_version_id": str(version_id)}).execute()

    # --- flags a person handles -------------------------------------------

    def list_open_flags(self) -> list[dict[str, Any]]:
        """Open flags by number, each with the version it holds, if any."""
        return (
            self.client.table("flags").select("*, versions(id)")
            .is_("resolved_at", "null").order("id").execute().data
        )

    def hold_candidate(self, version_id: str, address: str, message: str | None) -> int:
        """Hold a loaded version for a person under a candidate flag; returns the flag number."""
        return self.client.rpc("hold_candidate", {
            "p_version_id": str(version_id), "p_address": address, "p_message": message,
        }).execute().data

    def approve_candidate(self, version_id: str) -> int:
        """A person approves a held candidate; returns how many answers saw the retired version."""
        return self.client.rpc("approve_candidate", {"p_version_id": str(version_id)}).execute().data

    def raise_check_failed(self, source_key: str, address: str, message: str | None) -> int:
        """Report a watched address that cannot be reached; returns the flag number."""
        return self.client.rpc("raise_check_failed", {
            "p_source_key": source_key, "p_address": address, "p_message": message,
        }).execute().data

    def confirm_source(self, source_key: str) -> None:
        """A person confirms the source; resolves its overdue flag."""
        self.client.rpc("confirm_source", {"p_source_key": source_key}).execute()

    def raise_overdue_flags(self, max_age_days: int) -> int:
        """Flag sources not confirmed within max_age_days; returns how many flags were raised."""
        return self.client.rpc(
            "raise_overdue_flags", {"p_max_age": f"{int(max_age_days)} days"}
        ).execute().data

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

    def versions_seen(self, answer_id: str) -> list[dict[str, Any]]:
        """Source key, label and status of each version the answer saw."""
        rows = (
            self.client.table("answer_versions").select("versions(source_key, version_label, status)")
            .eq("answer_id", str(answer_id)).execute().data
        )
        return [row["versions"] for row in rows]

    def answers_that_saw(self, version_id: str) -> list[dict[str, Any]]:
        """Answers that saw the version, newest first, each with the other versions it saw."""
        return self.client.rpc("answers_that_saw", {"p_version_id": str(version_id)}).execute().data

    # --- evaluation ---------------------------------------------------------

    def get_eval_questions(self) -> list[dict[str, Any]]:
        return self.client.table("eval_questions").select("*").execute().data

    def insert_eval_run(self, run_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.table("eval_runs").insert(run_data).execute().data[0]

    def list_eval_runs(self) -> list[dict[str, Any]]:
        return self.client.table("eval_runs").select("*").execute().data
