"""Eval questions, their required sources and facts, runs and results, on a real Postgres."""
from __future__ import annotations

import pytest

from tests.db.conftest import make_source, make_version

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
        "where table_name in ('eval_questions', 'eval_question_facts') "
        "and data_type in ('json', 'jsonb')").fetchall()
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
