from app.retrieval.query_parser import QueryParser


def test_detect_known_provider():
    parser = QueryParser(known_providers=["Provider X", "Provider Y", "GridCo"])
    result = parser.parse("How do I wire component A for Provider X?")
    assert result.detected_provider == "Provider X"


def test_detect_no_provider():
    parser = QueryParser(known_providers=["Provider X", "Provider Y"])
    result = parser.parse("What is the general wiring standard?")
    assert result.detected_provider is None


def test_case_insensitive_match():
    parser = QueryParser(known_providers=["Provider X"])
    result = parser.parse("Rules for provider x installations")
    assert result.detected_provider == "Provider X"


def test_query_preserved():
    parser = QueryParser(known_providers=[])
    result = parser.parse("How do I install a meter?")
    assert result.original_question == "How do I install a meter?"


def test_filters_dict():
    parser = QueryParser(known_providers=["GridCo"])
    result = parser.parse("GridCo compliance requirements")
    filters = result.to_filters()
    assert filters["grid_provider"] == "GridCo"


def test_filters_empty_when_no_match():
    parser = QueryParser(known_providers=["GridCo"])
    result = parser.parse("General wiring standards")
    filters = result.to_filters()
    assert "grid_provider" not in filters
