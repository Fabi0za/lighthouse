from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    reducto_api_key: str
    anthropic_api_key: str = ""
    cohere_api_key: str = ""
    embedding_model: str = "embed-v5.0-pro"
    embedding_dimensions: int = 1536
    llm_model: str = "claude-sonnet-4-6"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 40
    rerank_top_n: int = 8
    rerank_model: str = "rerank-v3.5"
    judge_model: str = "claude-haiku-5-5"  # judges eval answers against their facts
    embed_rate_limit_wait_seconds: int = 61  # wait after a rate-limit error before retrying a batch
    embed_rate_limit_retries: int = 5
    confirmation_max_age_days: int = 180  # a source not confirmed for longer is flagged overdue

    model_config = {"env_file": ".env"}


def get_settings() -> Settings:
    return Settings()
