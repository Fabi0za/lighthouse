from app.generation.prompts import build_system_prompt, build_user_prompt


def test_system_prompt_contains_key_instructions():
    prompt = build_system_prompt()
    assert "only" in prompt.lower() and "provided context" in prompt.lower()
    assert "cite" in prompt.lower()
    assert "nicht genügend informationen" in prompt.lower()
    assert "higher rank" in prompt.lower()


def test_user_prompt_contains_question_and_context():
    chunks = [
        {
            "content": "Wire component X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "level": "operator",
            "version_title": "Manual A",
            "rank": 2,
        },
        {
            "content": "General wiring standards require grounding.",
            "section_title": "Standards",
            "page_number": 2,
            "level": "national",
            "version_title": "Regulations",
            "rank": 1,
        },
    ]
    prompt = build_user_prompt("How do I wire component X?", chunks)
    assert "How do I wire component X?" in prompt
    assert "Wire component X to terminal Y." in prompt
    assert "Manual A" in prompt
    assert "(Level: operator, Rank: 2)" in prompt
    assert "(Level: national, Rank: 1)" in prompt


def test_user_prompt_empty_context():
    prompt = build_user_prompt("Some question?", [])
    assert "Some question?" in prompt
    assert "no context" in prompt.lower() or "no relevant" in prompt.lower()


def test_display_title():
    from app.generation.prompts import display_title
    assert display_title("T", "V1.3") == "T (V1.3)"
    assert display_title("T", None) == "T"


def test_user_prompt_shows_title_and_label():
    chunk = {"content": "c", "section_title": "S", "page_number": 1, "level": "operator", "rank": 2,
             "version_title": "T", "version_label": "V1.3"}
    assert "[Source 1] T (V1.3) — S, Page 1" in build_user_prompt("q", [chunk])


def test_source_line_with_and_without_section():
    from app.generation.prompts import source_line
    chunk = {"version_title": "T", "version_label": "V1.3", "section_title": "S", "page_number": 3}
    assert source_line(chunk) == "T (V1.3) — S, Page 3"
    assert source_line({**chunk, "section_title": ""}) == "T (V1.3), Page 3"


def test_user_prompt_without_section_falls_back_to_page():
    chunk = {"content": "c", "section_title": "", "page_number": 3, "level": "operator", "rank": 2,
             "version_title": "T", "version_label": "V1.3"}
    prompt = build_user_prompt("q", [chunk])
    assert "[Source 1] T (V1.3), Page 3 (" in prompt
    assert " — ," not in prompt


def test_prompt_shows_the_header_once():
    chunk = {"content": "Steuerdraht 2 ist optional.", "section_title": "S", "page_number": 1,
             "level": "operator", "rank": 2, "version_title": "T", "version_label": "V1.3"}
    prompt = build_user_prompt("q", [chunk])
    assert prompt.count("T (V1.3) — S") == 1
    assert "[Source 1] T (V1.3) — S, Page 1 (Level: operator, Rank: 2)\nSteuerdraht 2 ist optional." in prompt


def test_system_prompt_keeps_its_rules():
    prompt = build_system_prompt()
    for kept in ("Always respond in German", "Answer based ONLY on the provided context",
                 "Cite every claim with [Document Title (Version Label), Section, Page X]",
                 "Ich habe nicht genügend Informationen, um diese Frage sicher zu beantworten.",
                 "End your response with a confidence assessment: high, medium, or low."):
        assert kept in prompt, kept
    assert "assistant that answers from the provided documents" in prompt



def test_citation_rule_asks_for_the_version_label():
    rule = next(line for line in build_system_prompt().splitlines() if line.startswith("3. "))
    assert "[Document Title (Version Label), Section, Page X]" in rule
    assert "exactly as shown in the source line" in rule
    assert "no label" in rule


def test_only_the_citation_rule_changed():
    rules = [line for line in build_system_prompt().splitlines() if line[:2] in {f"{n}." for n in range(1, 8)}]
    assert len(rules) == 7
