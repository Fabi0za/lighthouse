"""Indexing settings: their checks, and no mixing among current versions."""
from __future__ import annotations

import pytest

from tests.db.conftest import make_reference_rows, make_source, make_version
from tests.db.test_functions import promote

psycopg = pytest.importorskip("psycopg")
from psycopg import errors


def _settings(conn, key="k", model="m", dimensions=1536, size=500, overlap=50, chunker=1):
    conn.execute("insert into indexing_settings values (%s, %s, %s, %s, %s, %s)",
                 (key, model, dimensions, size, overlap, chunker))


def test_dimensions_must_match_the_vector_column(pg):
    with pytest.raises(errors.CheckViolation):
        _settings(pg, dimensions=1024)


@pytest.mark.parametrize("size, overlap", [(500, 500), (500, -1), (0, 0)])
def test_overlap_below_chunk_size(pg, size, overlap):
    with pytest.raises(errors.CheckViolation):
        _settings(pg, size=size, overlap=overlap)


def test_chunker_version_positive(pg):
    with pytest.raises(errors.CheckViolation):
        _settings(pg, chunker=0)


def test_settings_key_format(pg):
    with pytest.raises(errors.CheckViolation):
        _settings(pg, key="Embed V5")


def test_same_values_under_two_keys_refused(pg):
    _settings(pg, key="k1")
    with pytest.raises(errors.UniqueViolation):
        _settings(pg, key="k2")


def test_version_needs_known_settings(pg):
    with pytest.raises(errors.ForeignKeyViolation):
        make_version(pg, make_source(pg), indexing_settings_key="unknown")


def test_settings_of_a_version_cannot_change(pg):
    v = make_version(pg, make_source(pg))
    with pytest.raises(errors.CheckViolation):
        pg.execute("update versions set indexing_settings_key = 'test-b' where id = %s", (v,))


def test_mixed_settings_cannot_be_current(pg):
    a, b = make_source(pg, key="a"), make_source(pg, key="b")
    promote(pg, make_version(pg, a, text_sha256="t1", indexing_settings_key="test-a"))
    with pytest.raises(errors.CheckViolation), pg.transaction():  # savepoint: the test goes on
        promote(pg, make_version(pg, b, text_sha256="t2", indexing_settings_key="test-b"))
    promote(pg, make_version(pg, b, text_sha256="t3", indexing_settings_key="test-a"))


def test_same_source_can_move_to_new_settings_when_alone(pg):
    s = make_source(pg)
    promote(pg, make_version(pg, s, text_sha256="t1", indexing_settings_key="test-a"))
    v2 = make_version(pg, s, text_sha256="t2", indexing_settings_key="test-b")
    promote(pg, v2)
    assert pg.execute("select status from versions where id = %s", (v2,)).fetchone()[0] == "current"


def test_current_settings_keys(pg):
    make_reference_rows(pg)
    a = make_source(pg, key="a")
    promote(pg, make_version(pg, a, text_sha256="t1"))
    make_version(pg, a, text_sha256="t2", indexing_settings_key="test-b")  # loading, not current
    rows = pg.execute("select distinct indexing_settings_key from versions where status = 'current'").fetchall()
    assert rows == [("test-a",)]


# --- answer settings ---------------------------------------------------------

def test_answer_needs_known_settings(pg):
    from tests.db.conftest import answer_json
    make_reference_rows(pg)
    for over in ({"indexing_settings_key": "unknown"}, {"answer_settings_key": "unknown"}):
        with pytest.raises(errors.ForeignKeyViolation), pg.transaction():
            pg.execute("select log_answer(%s::jsonb, '{}'::uuid[])", (answer_json(**over),))


def test_answer_records_its_settings(pg):
    from tests.db.conftest import answer_json
    make_reference_rows(pg)
    a = pg.execute("select log_answer(%s::jsonb, '{}'::uuid[])", (answer_json(),)).fetchone()[0]
    row = pg.execute("select indexing_settings_key, answer_settings_key from answers where id = %s", (a,)).fetchone()
    assert row == ("test-a", "test-answers")


@pytest.mark.parametrize("top_k, top_n", [(8, 40), (0, 0)])
def test_rerank_top_n_not_above_top_k(pg, top_k, top_n):
    with pytest.raises(errors.CheckViolation):
        pg.execute("insert into answer_settings values ('x', %s, %s, 'r', 'a', 1)", (top_k, top_n))


def test_answers_have_no_model_used_or_formatted_answer(pg):
    cols = {r[0] for r in pg.execute(
        "select column_name from information_schema.columns where table_name = 'answers'")}
    assert {"indexing_settings_key", "answer_settings_key"} <= cols
    assert not cols & {"model_used", "formatted_answer"}
