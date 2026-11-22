"""Version lifecycle functions on a real Postgres: load, fail, retry, discard, promote, reject."""
from __future__ import annotations

import json

import pytest

from tests.db.conftest import answer_json, make_flag, make_source, make_version
from tests.db.test_functions import add_chunk, chunk_count, doc, promote

psycopg = pytest.importorskip("psycopg")
from psycopg import errors


def begin(conn, source_key, file_sha256="f1", title="Doc", label=None, obtained_from=None, page_limit=None,
          settings="test-a", fingerprint=True):
    """begin_load, then the text fingerprint as load_version sets it before chunking."""
    v = str(conn.execute("select begin_load(%s, %s, %s, %s, %s, %s, %s)",
                         (source_key, title, label, obtained_from, page_limit, file_sha256, settings)
                         ).fetchone()[0])
    if fingerprint:
        conn.execute("update versions set text_sha256 = %s where id = %s", (f"t-{file_sha256}", v))
    return v


def fail(conn, version_id, reason="load_failed", file="data/a.pdf", message="rate limit"):
    return conn.execute("select fail_load(%s, %s, %s, %s)", (version_id, reason, file, message)).fetchone()[0]


def flags_of(conn, source_key):
    cur = conn.execute("select * from flags where source_key = %s order by id", (source_key,))
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def flag_of(conn, version_id):
    return next(f for f in flags_of(conn, doc(conn, version_id)["source_key"])
                if f["id"] == doc(conn, version_id)["flag_id"])


# --- begin, fail, retry, discard -------------------------------------------

def test_begin_load_creates_loading_version_without_flag(pg):
    s = make_source(pg)
    v = begin(pg, s, label="V1", obtained_from="https://example.org/a.pdf", page_limit=4, fingerprint=False)
    row = doc(pg, v)
    assert (row["status"], row["flag_id"], row["version_label"], row["page_limit"]) == ("loading", None, "V1", 4)
    assert flags_of(pg, s) == []


def test_begin_load_resumes_same_bytes(pg):
    s = make_source(pg)
    v = begin(pg, s, file_sha256="f1")
    add_chunk(pg, v)  # left by the interrupted attempt
    assert begin(pg, s, file_sha256="f1") == v
    assert chunk_count(pg, v) == 0
    assert pg.execute("select count(*) from versions where source_key = %s", (s,)).fetchone()[0] == 1


def test_fail_load_raises_one_flag(pg):
    s = make_source(pg)
    v = begin(pg, s)
    first = fail(pg, v, message="rate limit")
    assert begin(pg, s) == v  # retry with the same bytes
    second = fail(pg, v, reason="parse_failed", message="timeout")
    assert first == second
    flags = flags_of(pg, s)
    assert len(flags) == 1
    f = flags[0]
    assert (f["kind"], f["reason"], f["resolved_at"]) == ("check_failed", "parse_failed", None)
    assert f["detail"] == {"file": "data/a.pdf", "message": "timeout"}
    assert doc(pg, v)["status"] == "failed"


def test_retry_success_resolves_flag(pg):
    s = make_source(pg)
    v = begin(pg, s)
    fail(pg, v)
    assert begin(pg, s) == v
    assert doc(pg, v)["status"] == "loading"
    promote(pg, v)
    f = flag_of(pg, v)
    assert (f["resolution"], f["resolved_by"]) == ("fixed", "system")
    assert doc(pg, v)["status"] == "current"


def test_discard_removes_version_and_resolves_flag(pg):
    s = make_source(pg)
    v = begin(pg, s)
    add_chunk(pg, v)
    f = fail(pg, v)
    pg.execute("select discard_version(%s)", (v,))
    assert pg.execute("select count(*) from versions where id = %s", (v,)).fetchone()[0] == 0
    flag = next(x for x in flags_of(pg, s) if x["id"] == f)
    assert (flag["resolution"], flag["resolved_by"]) == ("fixed", "system")


def test_discard_refuses_current(pg):
    s = make_source(pg)
    v = begin(pg, s)
    promote(pg, v)
    with pytest.raises(errors.RaiseException):
        pg.execute("select discard_version(%s)", (v,))


# --- promote ---------------------------------------------------------------

def test_promote_from_loading_needs_no_flag(pg):
    s = make_source(pg)
    v = begin(pg, s, obtained_from="https://example.org/v1.pdf")
    assert promote(pg, v) == 0
    row = doc(pg, v)
    assert (row["status"], row["flag_id"]) == ("current", None)
    assert row["became_current_at"] is not None
    assert flags_of(pg, s) == []


def test_promote_leaves_source_alone(pg):
    s = make_source(pg, watch_address="https://example.org/watched.pdf")
    before = pg.execute("select watch_address, confirmed_at from sources where key = %s", (s,)).fetchone()
    promote(pg, begin(pg, s, obtained_from="https://example.org/elsewhere.pdf"))
    after = pg.execute("select watch_address, confirmed_at from sources where key = %s", (s,)).fetchone()
    assert after == before


def test_promote_retires_previous_and_counts_its_answers(pg):
    s = make_source(pg)
    v1 = make_version(pg, s, text_sha256="t1", file_sha256="f1")
    pg.execute("update versions set parsed_output = %s where id = %s", (json.dumps({"x": 1}), v1))
    add_chunk(pg, v1)
    promote(pg, v1)
    for _ in range(2):
        pg.execute("select log_answer(%s::jsonb, %s::uuid[])", (answer_json(), [v1]))
    v2 = make_version(pg, s, text_sha256="t2")
    add_chunk(pg, v2)
    assert promote(pg, v2) == 2
    old = doc(pg, v1)
    assert old["status"] == "retired"
    assert old["retired_at"] is not None
    assert chunk_count(pg, v1) == 0
    assert old["parsed_output"] == {"x": 1}
    assert (old["file_sha256"], old["text_sha256"]) == ("f1", "t1")
    assert doc(pg, v2)["status"] == "current"
    assert chunk_count(pg, v2) == 1


def test_failed_promotion_leaves_previous_current(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        s = make_source(conn)
        v1 = make_version(conn, s, text_sha256="t1")
        add_chunk(conn, v1)
        promote(conn, v1)
        v2 = make_version(conn, s, status="failed", text_sha256="t2")
        conn.commit()
        with pytest.raises(errors.RaiseException):
            promote(conn, v2)
        conn.rollback()
    with psycopg.connect(pg_db_url) as fresh:
        assert doc(fresh, v1)["status"] == "current"
        assert chunk_count(fresh, v1) == 1
        assert doc(fresh, v2)["status"] == "failed"


@pytest.mark.parametrize("status", ["current", "retired", "failed"])
def test_promote_refuses_other_statuses(pg, status):
    s = make_source(pg)
    d = make_version(pg, s, status=status, text_sha256="t1",
                     retired_at="2026-01-01" if status == "retired" else None)
    with pytest.raises(errors.RaiseException):
        promote(pg, d)


# --- reject ----------------------------------------------------------------

def test_reject_version(pg):
    s = make_source(pg)
    d = make_version(pg, s, status="held", text_sha256="t1")
    add_chunk(pg, d)
    pg.execute("select reject_version(%s)", (d,))
    row = doc(pg, d)
    assert row["status"] == "retired"
    assert row["became_current_at"] is None
    assert chunk_count(pg, d) == 0
    f = flag_of(pg, d)
    assert (f["resolution"], f["resolved_by"]) == ("rejected", "person")


def test_reject_requires_held(pg):
    s = make_source(pg)
    d = make_version(pg, s, text_sha256="t1")
    with pytest.raises(errors.RaiseException):
        pg.execute("select reject_version(%s)", (d,))


# --- candidates --------------------------------------------------------------

def hold(conn, version_id, address="https://example.org/v2.pdf", message="new file name on the listing page"):
    return conn.execute("select hold_candidate(%s, %s, %s)", (version_id, address, message)).fetchone()[0]


def test_hold_then_approve_sets_watch_address_and_confirms(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        s = make_source(conn, watch_address="https://example.org/v1.pdf")
        current = begin(conn, s, file_sha256="f1")
        promote(conn, current)
        conn.commit()
        before = conn.execute("select confirmed_at from sources where key = %s", (s,)).fetchone()[0]
        v = begin(conn, s, file_sha256="f2", obtained_from="https://example.org/v2.pdf")
        number = hold(conn, v)
        assert doc(conn, v)["status"] == "held"
        assert doc(conn, v)["flag_id"] == number
        conn.commit()

        assert conn.execute("select approve_candidate(%s)", (v,)).fetchone()[0] == 0
        conn.commit()

        assert doc(conn, v)["status"] == "current"
        assert doc(conn, current)["status"] == "retired"
        f = flag_of(conn, v)
        assert (f["kind"], f["reason"], f["resolution"], f["resolved_by"]) == (
            "candidate", "possible_successor", "promoted", "person")
        assert f["detail"] == {"address": "https://example.org/v2.pdf", "message": "new file name on the listing page"}
        watch, confirmed = conn.execute("select watch_address, confirmed_at from sources where key = %s",
                                        (s,)).fetchone()
        assert watch == "https://example.org/v2.pdf"
        assert before is None or confirmed > before


def test_approve_without_obtained_from_refused(pg):
    s = make_source(pg, watch_address="https://example.org/v1.pdf")
    v = begin(pg, s, obtained_from=None)
    hold(pg, v)
    with pytest.raises(errors.RaiseException):
        pg.execute("select approve_candidate(%s)", (v,))


def test_approve_requires_held(pg):
    s = make_source(pg)
    v = begin(pg, s, obtained_from="https://example.org/v2.pdf")
    with pytest.raises(errors.RaiseException):
        pg.execute("select approve_candidate(%s)", (v,))


def test_reject_held_candidate_through_hold(pg):
    s = make_source(pg)
    v = begin(pg, s)
    hold(pg, v)
    pg.execute("select reject_version(%s)", (v,))
    assert doc(pg, v)["status"] == "retired"
    assert flag_of(pg, v)["resolution"] == "rejected"


# --- resume after the fingerprint was set ---------------------------------------

def _fingerprint(conn, version_id, text_sha256):
    conn.execute("update versions set text_sha256 = %s, parsed_output = '{\"x\": 1}' where id = %s",
                 (text_sha256, version_id))


def test_resume_clears_fingerprint_and_parsed_output(pg):
    s = make_source(pg)
    v = begin(pg, s)
    _fingerprint(pg, v, "t-old")
    fail(pg, v)
    assert begin(pg, s, fingerprint=False) == v
    row = doc(pg, v)
    assert (row["text_sha256"], row["parsed_output"]) == (None, None)


def test_loading_version_may_be_fingerprinted_again(pg):
    s = make_source(pg)
    v = begin(pg, s)
    _fingerprint(pg, v, "t-old")
    _fingerprint(pg, v, "t-new")  # still loading: allowed
    assert doc(pg, v)["text_sha256"] == "t-new"


@pytest.mark.parametrize("status", ["held", "current", "retired", "failed"])
def test_fingerprint_fixed_once_past_loading(pg, status):
    s = make_source(pg)
    v = make_version(pg, s, status=status, text_sha256="t1",
                     retired_at="2026-01-01" if status == "retired" else None)
    with pytest.raises(errors.CheckViolation):
        pg.execute("update versions set text_sha256 = 't2' where id = %s", (v,))


@pytest.mark.parametrize("status", ["held", "current", "retired"])
def test_held_current_and_retired_need_a_fingerprint(pg, status):
    s = make_source(pg)
    v = begin(pg, s, fingerprint=False)
    with pytest.raises(errors.CheckViolation):
        pg.execute("update versions set status = %s, retired_at = %s where id = %s",
                   (status, "2026-01-01" if status == "retired" else None, v))
