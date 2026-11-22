from app.config import Settings
from app.ingestion.chunker import CHUNKER_VERSION
from app.settings_rows import indexing_settings_row


def _settings(**over):
    return Settings(_env_file=None, supabase_url="http://localhost", supabase_service_key="k",
                    reducto_api_key="k", **over)


def test_indexing_key_names_its_values():
    row = indexing_settings_row(_settings())
    assert row == {
        "key": f"embed-v5.0-pro-1536-500-50-c{CHUNKER_VERSION}",
        "embedding_model": "embed-v5.0-pro", "dimensions": 1536,
        "chunk_size": 500, "chunk_overlap": 50, "chunker_version": CHUNKER_VERSION,
    }


def test_indexing_key_is_normalised():
    row = indexing_settings_row(_settings(embedding_model="Embed V5/Pro"))
    assert row["key"].startswith("embed-v5-pro-1536-")


def test_different_values_give_different_keys():
    assert indexing_settings_row(_settings())["key"] != indexing_settings_row(_settings(chunk_size=400))["key"]


def test_answer_key_names_its_values():
    from app.generation.prompts import PROMPT_VERSION
    from app.settings_rows import answer_settings_row
    row = answer_settings_row(_settings())
    assert row == {
        "key": f"top40-rerank8-rerank-v3.5-claude-sonnet-4-6-p{PROMPT_VERSION}",
        "retrieval_top_k": 40, "rerank_top_n": 8, "rerank_model": "rerank-v3.5",
        "answer_model": "claude-sonnet-4-6", "prompt_version": PROMPT_VERSION,
    }
