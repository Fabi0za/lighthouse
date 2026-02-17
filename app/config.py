from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_key: str
    reducto_api_key: str
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 20
    rerank_top_n: int = 8

    model_config = {"env_file": ".env"}


def get_settings() -> Settings:
    return Settings()
