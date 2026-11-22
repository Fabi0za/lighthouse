from app.retrieval.query_parser import QueryParser


def test_detect_known_scope():
    parser = QueryParser(known_scopes=["BKW", "EKZ"])
    result = parser.parse("Was gilt im Netz der BKW für Steuerlösungen?")
    assert result.detected_scope == "BKW"


def test_detect_no_scope():
    parser = QueryParser(known_scopes=["BKW", "EKZ"])
    result = parser.parse("Was gilt schweizweit für Steuerlösungen?")
    assert result.detected_scope is None


def test_case_insensitive_match():
    parser = QueryParser(known_scopes=["EKZ"])
    result = parser.parse("Regeln der ekz für Speicher")
    assert result.detected_scope == "EKZ"


def test_query_preserved():
    parser = QueryParser(known_scopes=[])
    result = parser.parse("Wie wird ein Zähler montiert?")
    assert result.original_question == "Wie wird ein Zähler montiert?"


def test_filters_dict():
    parser = QueryParser(known_scopes=["BKW"])
    assert parser.parse("BKW Vorgaben").to_filters() == {"scope": "BKW"}


def test_filters_empty_when_no_match():
    parser = QueryParser(known_scopes=["BKW"])
    assert parser.parse("Allgemeine Vorgaben").to_filters() == {}
