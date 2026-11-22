from app.generation.formatter import ResponseFormatter


def test_format_response_extracts_sources():
    formatter = ResponseFormatter()
    raw_response = """The component should be wired to terminal Y [Manual A, Wiring, Page 5]. General standards also require grounding [Regulations, Standards, Page 2].

Confidence: high"""

    chunks = [
        {"version_title": "Manual A", "section_title": "Wiring", "page_number": 5},
        {"version_title": "Regulations", "section_title": "Standards", "page_number": 2},
    ]

    result = formatter.format(raw_response, chunks)
    assert result["answer"] is not None
    assert result["confidence"] == "high"
    assert len(result["sources"]) == 2


def test_format_response_default_confidence():
    formatter = ResponseFormatter()
    raw_response = "Some answer without confidence."
    result = formatter.format(raw_response, [])
    assert result["confidence"] == "low"


def test_format_response_refusal():
    formatter = ResponseFormatter()
    raw_response = "I don't have enough information to answer this confidently."
    result = formatter.format(raw_response, [])
    assert "don't have enough information" in result["answer"]
    assert result["confidence"] == "low"


def test_sources_show_title_and_label():
    chunks = [{"version_title": "T", "version_label": "V1.3", "section_title": "S", "page_number": 1}]
    sources = ResponseFormatter().format("Antwort", chunks)["sources"]
    assert sources == [{"version_title": "T (V1.3)", "section": "S", "page": 1}]
