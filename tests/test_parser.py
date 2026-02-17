import io

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from app.ingestion.parser import ReductoParser


@pytest.fixture
def parser():
    return ReductoParser(api_key="test-key")


@pytest.mark.asyncio
async def test_parse_pdf_returns_sections(parser):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "blocks": [
                {"type": "header", "content": "Chapter 1: Overview", "page": 1},
                {"type": "text", "content": "This is the overview section content.", "page": 1},
                {"type": "header", "content": "Chapter 2: Wiring", "page": 3},
                {"type": "text", "content": "Wiring instructions go here.", "page": 3},
            ]
        }
    }

    with (
        patch("builtins.open", mock_open(read_data=b"fake pdf")),
        patch.object(parser.client, "post", new_callable=AsyncMock, return_value=mock_response),
    ):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert len(sections) == 2
        assert sections[0]["title"] == "Chapter 1: Overview"
        assert sections[0]["page"] == 1
        assert "overview section content" in sections[0]["content"]
        assert sections[1]["title"] == "Chapter 2: Wiring"


@pytest.mark.asyncio
async def test_parse_pdf_preserves_raw_output(parser):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "blocks": [
                {"type": "text", "content": "Some content", "page": 1},
            ]
        }
    }

    with (
        patch("builtins.open", mock_open(read_data=b"fake pdf")),
        patch.object(parser.client, "post", new_callable=AsyncMock, return_value=mock_response),
    ):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert raw_output == mock_response.json.return_value


@pytest.mark.asyncio
async def test_parse_pdf_no_headers_uses_default(parser):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "blocks": [
                {"type": "text", "content": "Content without headers.", "page": 1},
            ]
        }
    }

    with (
        patch("builtins.open", mock_open(read_data=b"fake pdf")),
        patch.object(parser.client, "post", new_callable=AsyncMock, return_value=mock_response),
    ):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert len(sections) == 1
        assert sections[0]["title"] == "Untitled Section"
