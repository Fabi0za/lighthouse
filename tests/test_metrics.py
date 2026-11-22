from eval.metrics import (
    retrieval_recall,
    refusal_accuracy,
)


def test_retrieval_recall_by_source_key():
    chunks = [{"source_key": "a"}, {"source_key": "a"}, {"source_key": "c"}]
    assert retrieval_recall(["a", "b"], chunks) == 0.5
    assert retrieval_recall(["a"], chunks) == 1.0


def test_recall_zero_for_source_without_retrieved_chunk():
    assert retrieval_recall(["b"], [{"source_key": "a"}]) == 0.0


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
