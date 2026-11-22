from app.retrieval.query_parser import QueryParser


def test_detect_known_scope():
    parser = QueryParser(known_scopes=["bkw", "ekz"])
    assert parser.parse("Was gilt im Netz der BKW für Steuerlösungen?").detected_scope == "bkw"


def test_detect_no_scope():
    parser = QueryParser(known_scopes=["bkw", "ekz"])
    assert parser.parse("Was gilt schweizweit für Steuerlösungen?").detected_scope is None


def test_scope_key_matches_whole_word_only():
    parser = QueryParser(known_scopes=["ekz"])
    assert parser.parse("Bekzahl der Anlage").detected_scope is None
    assert parser.parse("Regeln der EKZ für Speicher").detected_scope == "ekz"


def test_hyphenated_key_matches_words_with_space_or_hyphen():
    parser = QueryParser(known_scopes=["be-ju-so"])
    assert parser.parse("Vorgaben für BE JU SO").detected_scope == "be-ju-so"
    assert parser.parse("Vorgaben für be-ju-so").detected_scope == "be-ju-so"


def test_query_preserved():
    parser = QueryParser(known_scopes=[])
    assert parser.parse("Wie wird ein Zähler montiert?").original_question == "Wie wird ein Zähler montiert?"
