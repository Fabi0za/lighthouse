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
        assert sections[0]["title"] == ""  # no heading: empty, citations fall back to the page


RAW_WITH_LINKS = {
    "job_id": "j1", "pdf_url": "https://parser.example/pdf?sig=1", "studio_link": "https://parser.example/s/1",
    "usage": {"pages": 2},
    "result": {"type": "full", "chunks": [{"content": "c", "blocks": [
        {"type": "Text", "content": "Steuerdraht 2 ist optional", "bbox": {"page": 1},
         "image_url": "https://parser.example/img/1"},
    ]}]},
}


def test_strip_links_removes_parser_urls_only():
    from app.ingestion.parser import strip_links
    stripped = strip_links(RAW_WITH_LINKS)
    assert "pdf_url" not in stripped and "studio_link" not in stripped
    block = stripped["result"]["chunks"][0]["blocks"][0]
    assert "image_url" not in block
    assert block["content"] == "Steuerdraht 2 ist optional"
    assert (stripped["job_id"], stripped["usage"]) == ("j1", {"pages": 2})
    assert "pdf_url" in RAW_WITH_LINKS  # the input is not changed


def test_sections_unchanged_by_strip_links():
    import json
    from pathlib import Path
    from app.ingestion.parser import strip_links
    cached = sorted((Path(__file__).resolve().parent.parent / "plans-local" / "parsed").glob("*.json"))
    if not cached:
        pytest.skip("no cached parser output on this machine")
    p = ReductoParser(api_key="unused")
    for f in cached:
        raw = json.loads(f.read_text(encoding="utf-8"))
        assert p._extract_sections(strip_links(raw)) == p._extract_sections(raw), f.name


def _raw(*blocks):
    return {"result": {"chunks": [{"blocks": [
        {"type": t, "content": c, "bbox": {"page": p}} for t, c, p in blocks]}]}}


def test_page_header_is_page_furniture():
    raw = _raw(("Section Header", "4. Steuern oder Sperren", 1),
               ("Text", "Neue Anlagen werden nicht mehr gesteuert.", 1),
               ("Header", "BKW Energie AG Netzanschluss-Management", 2),
               ("Text", "Der Steuer-Überstromunterbrecher ist vorzubereiten.", 2))
    sections = ReductoParser(api_key="unused")._extract_sections(raw)
    assert [s["title"] for s in sections] == ["4. Steuern oder Sperren"]  # no section starts at the header
    assert "BKW Energie AG" not in sections[0]["content"]                # and its text is not content
    assert "vorzubereiten" in sections[0]["content"]


def test_old_rule_still_available_for_comparison():
    from app.ingestion.parser import HEADING_TYPES, PAGE_FURNITURE
    raw = _raw(("Header", "BKW Energie AG Netzanschluss", 1), ("Text", "Ein ausreichend langer Text.", 1))
    old = ReductoParser(api_key="unused")._extract_sections(
        raw, heading_types=HEADING_TYPES | {"Header"}, page_furniture=PAGE_FURNITURE - {"Header"})
    assert [s["title"] for s in old] == ["BKW Energie AG Netzanschluss"]
