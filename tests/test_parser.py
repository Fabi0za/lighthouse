import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from app.ingestion.parser import ReductoParser


@pytest.fixture
def parser():
    return ReductoParser(api_key="test-key")


@pytest.mark.asyncio
async def test_parse_pdf_returns_sections(parser):
    mock_upload = MagicMock()
    mock_upload.status_code = 200
    mock_upload.json.return_value = {"file_id": "reducto://abc123"}

    mock_parse = MagicMock()
    mock_parse.status_code = 200
    mock_parse.json.return_value = {
        "result": {
            "type": "full",
            "chunks": [
                {
                    "content": "Chapter 1 content",
                    "blocks": [
                        {"type": "Title", "content": "Chapter 1: Overview", "bbox": {"page": 1}},
                        {"type": "Text", "content": "This is the overview section content.", "bbox": {"page": 1}},
                    ],
                },
                {
                    "content": "Chapter 2 content",
                    "blocks": [
                        {"type": "Section Header", "content": "Chapter 2: Wiring", "bbox": {"page": 3}},
                        {"type": "Text", "content": "Wiring instructions go here.", "bbox": {"page": 3}},
                    ],
                },
            ],
        }
    }

    with (
        patch("builtins.open", mock_open(read_data=b"fake pdf")),
        patch.object(parser.client, "post", new_callable=AsyncMock, side_effect=[mock_upload, mock_parse]),
    ):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert len(sections) == 2
        assert sections[0]["title"] == "Chapter 1: Overview"
        assert sections[0]["page"] == 1
        assert "overview section content" in sections[0]["content"]
        assert sections[1]["title"] == "Chapter 2: Wiring"


@pytest.mark.asyncio
async def test_parse_pdf_preserves_raw_output(parser):
    mock_upload = MagicMock()
    mock_upload.status_code = 200
    mock_upload.json.return_value = {"file_id": "reducto://abc123"}

    expected_raw = {
        "result": {
            "type": "full",
            "chunks": [
                {
                    "content": "Some content",
                    "blocks": [
                        {"type": "Text", "content": "Some content", "bbox": {"page": 1}},
                    ],
                }
            ],
        }
    }

    mock_parse = MagicMock()
    mock_parse.status_code = 200
    mock_parse.json.return_value = expected_raw

    with (
        patch("builtins.open", mock_open(read_data=b"fake pdf")),
        patch.object(parser.client, "post", new_callable=AsyncMock, side_effect=[mock_upload, mock_parse]),
    ):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert raw_output == expected_raw


@pytest.mark.asyncio
async def test_parse_pdf_no_headers_uses_default(parser):
    mock_upload = MagicMock()
    mock_upload.status_code = 200
    mock_upload.json.return_value = {"file_id": "reducto://abc123"}

    mock_parse = MagicMock()
    mock_parse.status_code = 200
    mock_parse.json.return_value = {
        "result": {
            "type": "full",
            "chunks": [
                {
                    "content": "Content without headers.",
                    "blocks": [
                        {"type": "Text", "content": "Content without headers.", "bbox": {"page": 1}},
                    ],
                }
            ],
        }
    }

    with (
        patch("builtins.open", mock_open(read_data=b"fake pdf")),
        patch.object(parser.client, "post", new_callable=AsyncMock, side_effect=[mock_upload, mock_parse]),
    ):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert len(sections) == 1
        assert sections[0]["title"] == "Untitled Section"
