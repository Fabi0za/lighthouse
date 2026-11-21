import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.generation.llm import LLMClient


@pytest.fixture
def anthropic_client():
    return LLMClient(
        provider="anthropic",
        api_key="test-key",
        model="claude-sonnet-4-6",
    )


@pytest.fixture
def openai_client():
    return LLMClient(
        provider="openai",
        api_key="test-key",
        model="gpt-4o",
    )


def test_anthropic_client_init(anthropic_client):
    assert anthropic_client.provider == "anthropic"
    assert anthropic_client.model == "claude-sonnet-4-6"


def test_openai_client_init(openai_client):
    assert openai_client.provider == "openai"


@pytest.mark.asyncio
async def test_anthropic_generate(anthropic_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": "The answer is 42."}]
    }
    with patch.object(
        anthropic_client.client, "post", new_callable=AsyncMock, return_value=mock_response
    ):
        result = await anthropic_client.generate(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is the answer?",
        )
        assert result == "The answer is 42."


@pytest.mark.asyncio
async def test_openai_generate(openai_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "The answer is 42."}}]
    }
    with patch.object(
        openai_client.client, "post", new_callable=AsyncMock, return_value=mock_response
    ):
        result = await openai_client.generate(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is the answer?",
        )
        assert result == "The answer is 42."


@pytest.mark.asyncio
async def test_anthropic_request_has_no_temperature(anthropic_client):
    mock_response = MagicMock()
    mock_response.json.return_value = {"content": [{"type": "text", "text": "ok"}]}
    post = AsyncMock(return_value=mock_response)
    with patch.object(anthropic_client.client, "post", post):
        await anthropic_client.generate(system_prompt="s", user_prompt="u")
    assert "temperature" not in post.call_args.kwargs["json"]


@pytest.mark.asyncio
async def test_anthropic_generate_skips_thinking_block(anthropic_client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": "The answer is 42."},
        ]
    }
    with patch.object(anthropic_client.client, "post", AsyncMock(return_value=mock_response)):
        result = await anthropic_client.generate(system_prompt="s", user_prompt="u")
    assert result == "The answer is 42."


@pytest.mark.asyncio
async def test_anthropic_generate_raises_without_text(anthropic_client):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}],
        "stop_reason": "max_tokens",
    }
    with patch.object(anthropic_client.client, "post", AsyncMock(return_value=mock_response)):
        with pytest.raises(RuntimeError, match="stop_reason=max_tokens"):
            await anthropic_client.generate(system_prompt="s", user_prompt="u")
