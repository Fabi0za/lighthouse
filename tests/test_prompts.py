from app.generation.prompts import build_system_prompt, build_user_prompt


def test_system_prompt_contains_key_instructions():
    prompt = build_system_prompt()
    assert "only" in prompt.lower() and "provided context" in prompt.lower()
    assert "cite" in prompt.lower()
    assert "nicht genügend informationen" in prompt.lower()
    assert "hierarchy" in prompt.lower() or "higher-priority" in prompt.lower()


def test_user_prompt_contains_question_and_context():
    chunks = [
        {
            "content": "Wire component X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "level": "operator",
            "version_title": "Manual A",
            "authority_rank": 2,
        },
        {
            "content": "General wiring standards require grounding.",
            "section_title": "Standards",
            "page_number": 2,
            "level": "national",
            "version_title": "Regulations",
            "authority_rank": 1,
        },
    ]
    prompt = build_user_prompt("How do I wire component X?", chunks)
    assert "How do I wire component X?" in prompt
    assert "Wire component X to terminal Y." in prompt
    assert "Manual A" in prompt
    assert "(Type: operator, Priority: 2)" in prompt
    assert "(Type: national, Priority: 1)" in prompt


def test_user_prompt_empty_context():
    prompt = build_user_prompt("Some question?", [])
    assert "Some question?" in prompt
    assert "no context" in prompt.lower() or "no relevant" in prompt.lower()
