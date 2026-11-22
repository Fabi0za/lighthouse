"""Flags: running number, fixed lists for kind, reason, resolution and resolver, detail shape."""
from __future__ import annotations

import itertools
import json

import pytest

from tests.db.conftest import make_flag, make_source, make_version, resolve_flag

psycopg = pytest.importorskip("psycopg")
from psycopg import errors

PAIRS = {
    ("candidate", "possible_successor"),
    ("check_failed", "unreachable"),
    ("check_failed", "parse_failed"),
    ("check_failed", "load_failed"),
    ("confirmation_overdue", "overdue"),
}
KINDS = sorted({k for k, _ in PAIRS})
REASONS = sorted({r for _, r in PAIRS})
DETAIL_FOR = {
    "possible_successor": {"address": "https://example.org/v2.pdf"},
    "unreachable": {"address": "https://example.org/v2.pdf"},
    "parse_failed": {"file": "data/a.pdf"},
    "load_failed": {"file": "data/a.pdf"},
    "overdue": {"address": None},
}


def test_flag_numbers_run(pg):
    s = make_source(pg)
    first, second = make_flag(pg, s), make_flag(pg, s)
    assert isinstance(first, int) and second == first + 1


@pytest.mark.parametrize("kind, reason", list(itertools.product(KINDS, REASONS)))
def test_kind_reason_pairs(pg, kind, reason):
    s = make_source(pg)
    detail = json.dumps(DETAIL_FOR[reason])
    if (kind, reason) in PAIRS:
        make_flag(pg, s, kind, reason, detail)
    else:
        with pytest.raises(errors.CheckViolation):
            make_flag(pg, s, kind, reason, detail)


@pytest.mark.parametrize("kind, reason", [("new_version", "possible_successor"), ("candidate", "other")])
def test_unknown_kind_or_reason(pg, kind, reason):
    with pytest.raises(errors.CheckViolation):
        make_flag(pg, make_source(pg), kind, reason)


@pytest.mark.parametrize("resolution, resolved_by", [("dismissed", "person"), ("rejected", "admin")])
def test_unknown_resolution_or_resolver(pg, resolution, resolved_by):
    f = make_flag(pg, make_source(pg))
    with pytest.raises(errors.CheckViolation):
        resolve_flag(pg, f, resolution, resolved_by)


@pytest.mark.parametrize("sets", [
    "resolved_at = now()",
    "resolved_at = now(), resolution = 'rejected'",
    "resolution = 'rejected', resolved_by = 'person'",
])
def test_resolution_needs_all_three(pg, sets):
    f = make_flag(pg, make_source(pg))
    with pytest.raises(errors.CheckViolation):
        pg.execute(f"update flags set {sets} where id = %s", (f,))


def test_resolution_with_all_three(pg):
    f = make_flag(pg, make_source(pg))
    resolve_flag(pg, f, "rejected", "person")


@pytest.mark.parametrize("reason, detail, ok", [
    ("load_failed", {"file": "data/a.pdf"}, True),
    ("possible_successor", {"address": "u", "message": "m"}, True),
    ("load_failed", {}, False),
    ("load_failed", {"file": "a", "address": "u"}, False),
    ("load_failed", {"file": "a", "other": 1}, False),
    ("load_failed", {"address": "u"}, False),
    ("possible_successor", {"file": "a"}, False),
])
def test_detail_shape(pg, reason, detail, ok):
    kind = next(k for k, r in PAIRS if r == reason)
    s = make_source(pg)
    if ok:
        make_flag(pg, s, kind, reason, json.dumps(detail))
    else:
        with pytest.raises(errors.CheckViolation):
            make_flag(pg, s, kind, reason, json.dumps(detail))


def test_flag_not_resolvable_while_held(pg):
    s = make_source(pg)
    f = make_flag(pg, s)
    make_version(pg, s, flag_id=f)
    with pytest.raises(errors.CheckViolation):
        resolve_flag(pg, f)


def test_flag_resolvable_without_held_version(pg):
    resolve_flag(pg, make_flag(pg, make_source(pg)))
