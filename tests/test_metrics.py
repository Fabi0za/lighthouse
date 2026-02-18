import uuid

from eval.metrics import (
    retrieval_recall,
    refusal_accuracy,
)


def test_retrieval_recall_perfect():
    required_doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    retrieved_chunks = [
        {"document_id": required_doc_ids[0]},
        {"document_id": required_doc_ids[1]},
        {"document_id": str(uuid.uuid4())},
    ]
    score = retrieval_recall(required_doc_ids, retrieved_chunks)
    assert score == 1.0


def test_retrieval_recall_partial():
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    retrieved_chunks = [{"document_id": doc_a}]
    score = retrieval_recall([doc_a, doc_b], retrieved_chunks)
    assert score == 0.5


def test_retrieval_recall_none():
    score = retrieval_recall([str(uuid.uuid4())], [{"document_id": str(uuid.uuid4())}])
    assert score == 0.0


def test_refusal_accuracy_correct_refusal():
    assert refusal_accuracy(
        question_type="unanswerable",
        answer="I don't have enough information to answer this confidently.",
    ) is True


def test_refusal_accuracy_incorrect_answer_to_unanswerable():
    assert refusal_accuracy(
        question_type="unanswerable",
        answer="The wire should be connected to terminal X.",
    ) is False


def test_refusal_accuracy_correct_answer_to_answerable():
    assert refusal_accuracy(
        question_type="answerable",
        answer="The wire should be connected to terminal X.",
    ) is True


def test_refusal_accuracy_false_refusal():
    assert refusal_accuracy(
        question_type="answerable",
        answer="I don't have enough information to answer this confidently.",
    ) is False


def test_refusal_accuracy_german_refusal_detected():
    assert refusal_accuracy(
        question_type="unanswerable",
        answer="Ich habe nicht genügend Informationen, um diese Frage sicher zu beantworten.",
    ) is True


def test_refusal_accuracy_german_refusal_partial_phrase():
    assert refusal_accuracy(
        question_type="unanswerable",
        answer="Es gibt nicht genug Informationen in den Dokumenten.",
    ) is True


def test_refusal_accuracy_german_false_refusal():
    assert refusal_accuracy(
        question_type="answerable",
        answer="Ich habe nicht genügend Informationen, um diese Frage zu beantworten.",
    ) is False
