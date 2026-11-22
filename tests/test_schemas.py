from app.models.schemas import QueryRequest


def test_query_request():
    req = QueryRequest(question="How do I wire component X for Provider Y?")
    assert req.question == "How do I wire component X for Provider Y?"
