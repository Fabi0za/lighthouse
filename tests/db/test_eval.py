"""Eval questions, their required sources and facts, runs and results, on a real Postgres."""
from __future__ import annotations

import pytest

import json

from tests.db.conftest import answer_json, make_reference_rows, make_source, make_version

psycopg = pytest.importorskip("psycopg")
from psycopg import errors


def make_question(conn, key="bkw-steuerdraht-2", question_type="answerable",
                  case_type="changed_between_versions") -> str:
    conn.execute(
        "insert into eval_questions (key, question, question_type, case_type, expected_answer) "
        "values (%s, 'Q?', %s, %s, 'A.')", (key, question_type, case_type))
    return key


def add_fact(conn, question_key, position, text="Steuerdraht 2 ist optional"):
    conn.execute("insert into eval_question_facts (question_key, position, text) values (%s, %s, %s)",
                 (question_key, position, text))


# --- questions and facts -----------------------------------------------------

@pytest.mark.parametrize("key", ["Q1", "bkw steuerdraht", "bkw_q1", "-q1"])
def test_question_key_format(pg, key):
    with pytest.raises(errors.CheckViolation):
        make_question(pg, key=key)


@pytest.mark.parametrize("value, ok", [("answerable", True), ("unanswerable", True), ("other", False)])
def test_question_type_values(pg, value, ok):
    if ok:
        make_question(pg, question_type=value)
    else:
        with pytest.raises(errors.CheckViolation):
            make_question(pg, question_type=value)


@pytest.mark.parametrize("value, ok", [
    ("standard", True), ("changed_between_versions", True), ("not_covered", True),
    ("unknown_scope", True), ("Verkabelung", False)])
def test_case_type_values(pg, value, ok):
    if ok:
        make_question(pg, case_type=value)
    else:
        with pytest.raises(errors.CheckViolation):
            make_question(pg, case_type=value)


def test_facts_are_numbered_per_question(pg):
    q = make_question(pg)
    add_fact(pg, q, 1)
    with pytest.raises(errors.UniqueViolation), pg.transaction():
        add_fact(pg, q, 1)
    with pytest.raises(errors.CheckViolation):
        add_fact(pg, q, 0)


def test_eval_tables_have_no_json_columns(pg):
    rows = pg.execute(
        "select table_name, column_name from information_schema.columns "
        "where table_name like 'eval%%' and data_type in ('json', 'jsonb')").fetchall()
    assert rows == []


# --- required sources and review ---------------------------------------------

def require(conn, question_key, source_key, text_sha256):
    conn.execute("insert into eval_question_sources (question_key, source_key, written_from_text_sha256) "
                 "values (%s, %s, %s)", (question_key, source_key, text_sha256))


def to_review(conn):
    return conn.execute("select question_key, source_key, written_from_text_sha256, current_text_sha256 "
                        "from eval_questions_to_review order by 1, 2").fetchall()


def test_required_source_must_be_a_known_version(pg):
    s = make_source(pg)
    make_version(pg, s, status="current", text_sha256="t13")
    q = make_question(pg)
    with pytest.raises(errors.ForeignKeyViolation):
        require(pg, q, s, "unknown")


def test_question_on_the_current_version_needs_no_review(pg):
    s = make_source(pg)
    make_version(pg, s, status="current", text_sha256="t13")
    require(pg, make_question(pg), s, "t13")
    assert to_review(pg) == []


def test_question_on_a_retired_version_is_listed_for_review(pg):
    s = make_source(pg)
    make_version(pg, s, status="retired", retired_at="2026-01-01", text_sha256="t12")
    make_version(pg, s, status="current", text_sha256="t13")
    q = make_question(pg)
    require(pg, q, s, "t12")
    assert to_review(pg) == [(q, s, "t12", "t13")]


def test_source_without_current_version_is_listed(pg):
    s = make_source(pg)
    make_version(pg, s, status="retired", retired_at="2026-01-01", text_sha256="t12")
    q = make_question(pg)
    require(pg, q, s, "t12")
    assert to_review(pg) == [(q, s, "t12", None)]


# --- runs and results --------------------------------------------------------

def _answer(conn):
    make_reference_rows(conn)
    return str(conn.execute("select log_answer(%s::jsonb, '{}'::uuid[])", (answer_json(),)).fetchone()[0])


def _result(question_key, answer_id, correctness=1.0, error=None, facts=None, recall=1.0):
    return {"question_key": question_key, "answer_id": answer_id, "refusal_correct": True,
            "retrieval_recall": recall, "answer_correctness": correctness, "judge_error": error,
            "facts": facts or []}


def record(conn, results, notes=None):
    run = {"indexing_settings_key": "test-a", "answer_settings_key": "test-answers",
           "judge_model": "claude-haiku-5-5", "notes": notes, "results": results}
    return str(conn.execute("select record_eval_run(%s::jsonb)", (json.dumps(run),)).fetchone()[0])


def scores(conn, run_id):
    cur = conn.execute("select * from eval_run_scores where run_id = %s", (run_id,))
    cols = [c.name for c in cur.description]
    return dict(zip(cols, cur.fetchone()))


def test_record_eval_run_stores_run_results_and_facts(pg):
    q = make_question(pg)
    add_fact(pg, q, 1)
    add_fact(pg, q, 2, "Klemmen für Steuerdraht 1 und 0")
    a = _answer(pg)
    run = record(pg, [_result(q, a, 0.5, facts=[
        {"position": 1, "present": True, "reason": "named"},
        {"position": 2, "present": False, "reason": "missing"}])], notes="first")
    row = pg.execute("select judge_model, notes, indexing_settings_key, answer_settings_key from eval_runs "
                     "where id = %s", (run,)).fetchone()
    assert row == ("claude-haiku-5-5", "first", "test-a", "test-answers")
    assert pg.execute("select answer_id::text, answer_correctness from eval_results where run_id = %s",
                      (run,)).fetchone() == (a, 0.5)
    facts = pg.execute("select position, present from eval_fact_results where run_id = %s order by 1",
                       (run,)).fetchall()
    assert facts == [(1, True), (2, False)]


def test_result_needs_a_real_answer(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        make_reference_rows(conn)
        q = make_question(conn)
        conn.commit()
        with pytest.raises(errors.ForeignKeyViolation):
            record(conn, [_result(q, "00000000-0000-0000-0000-000000000000")])
        conn.rollback()
        assert conn.execute("select count(*) from eval_runs").fetchone()[0] == 0


def test_fact_result_needs_a_real_fact(pg):
    q = make_question(pg)
    with pytest.raises(errors.ForeignKeyViolation):
        record(pg, [_result(q, _answer(pg), facts=[{"position": 7, "present": True, "reason": "x"}])])


def test_scores_view_averages_non_null_values(pg):
    q1, q2 = make_question(pg, key="q1"), make_question(pg, key="q2", question_type="unanswerable")
    a = _answer(pg)
    run = record(pg, [_result(q1, a, 0.5, recall=1.0), _result(q2, a, None, recall=None)])
    s = scores(pg, run)
    assert (s["questions"], s["scored"], s["not_scored"]) == (2, 1, 0)
    assert (float(s["answer_correctness"]), float(s["retrieval_recall"])) == (0.5, 1.0)
    assert float(s["refusal_accuracy"]) == 1.0


def test_unscored_result_is_counted_not_averaged(pg):
    q1, q2 = make_question(pg, key="q1"), make_question(pg, key="q2")
    a = _answer(pg)
    run = record(pg, [_result(q1, a, 1.0), _result(q2, a, None, error="RuntimeError: judge refused")])
    s = scores(pg, run)
    assert (s["questions"], s["scored"], s["not_scored"]) == (2, 1, 1)
    assert float(s["answer_correctness"]) == 1.0


def test_judge_error_and_score_exclude_each_other(pg):
    q = make_question(pg)
    with pytest.raises(errors.CheckViolation):
        record(pg, [_result(q, _answer(pg), 1.0, error="both")])


def test_empty_run_scores_zero_questions(pg):
    make_reference_rows(pg)
    s = scores(pg, record(pg, []))
    assert (s["questions"], s["scored"], s["not_scored"]) == (0, 0, 0)
    assert s["answer_correctness"] is None


@pytest.mark.parametrize("recall", [1.5, -0.1])
def test_recall_out_of_range_refused(pg, recall):
    q = make_question(pg)
    with pytest.raises(errors.CheckViolation):
        record(pg, [_result(q, _answer(pg), recall=recall)])



# --- saving questions --------------------------------------------------------

def save(conn, key="q", question="Q?", facts=("a", "b"), sources=(), expected="A."):
    payload = {"key": key, "question": question, "question_type": "answerable", "case_type": "standard",
               "expected_answer": expected, "facts": list(facts),
               "sources": [{"source_key": s, "written_from_text_sha256": h} for s, h in sources]}
    conn.execute("select save_eval_question(%s::jsonb)", (json.dumps(payload),))


def test_save_eval_question_replaces_sources_and_facts(pg):
    s = make_source(pg)
    make_version(pg, s, status="retired", retired_at="2026-01-01", text_sha256="t12")
    make_version(pg, s, status="current", text_sha256="t13")
    save(pg, facts=("a", "b"), sources=[(s, "t12")])
    save(pg, facts=("c",), sources=[(s, "t13")], expected="B.")
    assert pg.execute("select position, text from eval_question_facts where question_key = 'q'").fetchall() == [
        (1, "c")]
    assert pg.execute("select written_from_text_sha256 from eval_question_sources").fetchall() == [("t13",)]
    assert pg.execute("select expected_answer from eval_questions where key = 'q'").fetchone()[0] == "B."


def test_facts_and_question_fixed_once_results_exist(pg):
    save(pg, facts=("a", "b"))
    record(pg, [_result("q", _answer(pg), 1.0, facts=[{"position": 1, "present": True, "reason": "r"}])])
    save(pg, facts=("a", "b"), expected="New expected answer.")  # unchanged facts: allowed
    for changed in ({"facts": ("a", "c")}, {"question": "Other?"}):
        with pytest.raises(errors.RaiseException), pg.transaction():
            save(pg, **changed)
