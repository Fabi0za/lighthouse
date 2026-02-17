import pytest
from app.config import Settings


@pytest.fixture
def test_settings():
    return Settings(
        supabase_url="http://localhost:54321",
        supabase_key="test-key",
        supabase_service_key="test-service-key",
        reducto_api_key="test-reducto-key",
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
    )
