import dataclasses
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypdf import PdfWriter

from app.ingestion.fingerprint import file_sha256

_spec = importlib.util.spec_from_file_location(
    "load_corpus", Path(__file__).resolve().parent.parent / "scripts" / "load_corpus.py"
)
lc = importlib.util.module_from_spec(_spec)
sys.modules["load_corpus"] = lc
_spec.loader.exec_module(lc)

ROOT = Path(__file__).resolve().parent.parent

REFERENCES = """
levels:
  - {key: national, rank: 1}
  - {key: operator, rank: 2, requires_scope: true}
scopes:
  - {key: x, name: X Netz}
  - {key: y, name: Y Netz}
"""


def _pdf(path: Path, pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200 + pages)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _corpus(tmp_path: Path, body: str) -> Path:
    """A corpus.yaml with body; the standard levels and scopes unless body defines its own."""
    p = tmp_path / "corpus.yaml"
    p.write_text(body if "levels:" in body else REFERENCES + body, encoding="utf-8")
    return p


def _db(**stored_source) -> MagicMock:
    db = MagicMock()
    db.list_source_keys.return_value = []
    db.find_source.return_value = stored_source or None
    return db


GOOD = """
sources:
  - key: national-rules
    level: national
    versions:
      - {path: a.pdf, title: "National rules 2025", obtained_from: "https://example.org/a.pdf"}
  - key: op-rules
    level: operator
    scopes: [x, y]
    watch_address: "https://example.org/op.pdf"
    versions:
      - {path: v1.pdf, title: "Operator rules", label: "V1"}
      - {path: v2.pdf, title: "Operator rules", label: "V2", max_pages: 4}
"""


def _files(tmp_path):
    _pdf(tmp_path / "a.pdf", 1)
    _pdf(tmp_path / "v1.pdf", 2)
    _pdf(tmp_path / "v2.pdf", 3)


# --- reading corpus.yaml -----------------------------------------------------

def test_load_corpus_reads_levels_scopes_sources_and_versions(tmp_path):
    _files(tmp_path)
    corpus = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    assert [(lv.key, lv.rank, lv.requires_scope) for lv in corpus.levels] == [
        ("national", 1, False), ("operator", 2, True)]
    assert [(sc.key, sc.name) for sc in corpus.scopes] == [("x", "X Netz"), ("y", "Y Netz")]
    national, operator = corpus.sources
    assert (national.key, national.level, national.scopes) == ("national-rules", "national", [])
    for gone in ("authority_rank", "title", "issuer", "listing_address"):
        assert not hasattr(national, gone), gone
    assert national.versions[0].obtained_from == "https://example.org/a.pdf"
    assert (national.watch_address, operator.watch_address) == (None, "https://example.org/op.pdf")
    assert (operator.key, operator.scopes) == ("op-rules", ["x", "y"])
    assert [v.path for v in operator.versions] == ["v1.pdf", "v2.pdf"]
    assert [v.label for v in operator.versions] == ["V1", "V2"]
    assert national.versions[0].label is None
    assert operator.versions[1].max_pages == 4
    assert operator.versions[0].obtained_from is None


def test_load_corpus_reports_all_problems(tmp_path):
    _pdf(tmp_path / "a.pdf")
    corpus = _corpus(tmp_path, """
sources:
  - {key: b, level: operator, versions: [{path: a.pdf, title: B}]}
  - {key: c, level: national, versions: [{path: missing.pdf, title: C}]}
  - {level: national, versions: [{path: a.pdf, title: D}]}
  - {key: e, level: national, versions: []}
  - {key: f, level: national, versions: [{path: a.pdf, title: F, max_pages: 0}]}
  - {key: Bad Key, level: national, versions: [{path: a.pdf, title: G}]}
""")
    with pytest.raises(ValueError) as e:
        lc.load_corpus(corpus, tmp_path)
    msg = str(e.value)
    assert "b: level 'operator' needs a scope" in msg
    assert "missing.pdf: file not found" in msg
    assert "missing key" in msg
    assert "e: no versions" in msg
    assert "max_pages must be a positive integer" in msg
    assert "Bad Key: key must be lowercase letters and digits joined by hyphens" in msg


def test_unknown_level_or_scope_is_reported(tmp_path):
    _pdf(tmp_path / "a.pdf")
    corpus = _corpus(tmp_path, """
sources:
  - {key: s, level: regional, scopes: [x, zz], versions: [{path: a.pdf, title: A}]}
""")
    with pytest.raises(ValueError) as e:
        lc.load_corpus(corpus, tmp_path)
    assert "s: unknown level 'regional'" in str(e.value)
    assert "s: unknown scope 'zz'" in str(e.value)


def test_levels_and_scopes_are_validated(tmp_path):
    corpus = _corpus(tmp_path, """
levels:
  - {key: national, rank: 1}
  - {key: Operator, rank: 0}
  - {key: other, rank: 1}
scopes:
  - {key: x}
sources: []
""")
    with pytest.raises(ValueError) as e:
        lc.load_corpus(corpus, tmp_path)
    msg = str(e.value)
    assert "level Operator: key must be lowercase words joined by hyphens" in msg
    assert "level Operator: rank must be a positive integer" in msg
    assert "level other: rank 1 used twice" in msg
    assert "scope x: missing name" in msg


def test_load_corpus_rejects_duplicate_source_keys(tmp_path):
    _pdf(tmp_path / "a.pdf")
    _pdf(tmp_path / "b.pdf", 2)
    corpus = _corpus(tmp_path, """
sources:
  - {key: same, level: national, versions: [{path: a.pdf, title: A}]}
  - {key: same, level: national, versions: [{path: b.pdf, title: B}]}
""")
    with pytest.raises(ValueError, match="source key listed twice"):
        lc.load_corpus(corpus, tmp_path)


def test_load_corpus_rejects_path_listed_twice(tmp_path):
    _pdf(tmp_path / "a.pdf")
    corpus = _corpus(tmp_path, """
sources:
  - {key: a, level: national, versions: [{path: a.pdf, title: A}, {path: a.pdf, title: A2}]}
""")
    with pytest.raises(ValueError, match="listed twice"):
        lc.load_corpus(corpus, tmp_path)


# --- dry run -----------------------------------------------------------------

def test_plan_skips_stored_files_and_says_cache_or_parse(tmp_path):
    _files(tmp_path)
    sources = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path).sources
    known = {file_sha256(tmp_path / "v1.pdf")}
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{file_sha256(tmp_path / 'v2.pdf')}.json").write_text("{}", encoding="utf-8")
    actions = {v.path: a for _, v, a in lc.plan(sources, known, tmp_path, parsed_cache=cache)}
    assert actions == {"a.pdf": "parse", "v1.pdf": "skip", "v2.pdf": "cache"}


def test_plan_without_cache_parses(tmp_path):
    _files(tmp_path)
    sources = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path).sources
    actions = {v.path: a for _, v, a in lc.plan(sources, set(), tmp_path)}
    assert set(actions.values()) == {"parse"}


# --- the checked-in corpus ---------------------------------------------------

def _repo_corpus() -> dict:
    return __import__("yaml").safe_load((ROOT / "corpus.yaml").read_text(encoding="utf-8"))


def test_repo_corpus_is_valid():
    """corpus.yaml lists BKW Vorgaben V1.2 before V1.3, with the labels the baseline uses."""
    data = _repo_corpus()
    vorgaben = [s for s in data["sources"] if s["key"] == "bkw-vorgaben-niederspannung"]
    assert len(vorgaben) == 1
    versions = vorgaben[0]["versions"]
    assert [v["path"] for v in versions] == [
        "data/BKW/DE_Vorgaben_BKW_V1.2.pdf", "data/BKW/20250521_DE_Vorgaben_BKW_V1.3.pdf"]
    assert [v["label"] for v in versions] == [
        "Version: V1.2, Gültigkeit 1. März 2025", "Version: V1.3, Gültig ab 21.05.2025"]
    ranks = {lv["key"]: lv["rank"] for lv in data["levels"]}
    assert ranks["operator"] > ranks["national"]  # higher rank wins: operator rules prevail
    assert all(lc.KEY_FORMAT.match(s["key"]) for s in data["sources"])
    assert len(data["sources"]) == 10


def test_repo_corpus_labels_match_the_baseline_script():
    spec = importlib.util.spec_from_file_location(
        "version_baseline_labels", ROOT / "scripts" / "experiments" / "version_baseline.py")
    vb = importlib.util.module_from_spec(spec)
    sys.modules["version_baseline_labels"] = vb
    spec.loader.exec_module(vb)
    labels = {v.get("label") for s in _repo_corpus()["sources"] for v in s["versions"]}
    assert {vb.V12_LABEL, vb.V13_LABEL} <= labels


# --- loading -----------------------------------------------------------------

async def test_load_all_saves_references_and_sources_and_loads_versions_in_order(tmp_path, capsys):
    _files(tmp_path)
    corpus = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    db = _db()
    db.find_source.side_effect = [None, {"key": "op-rules", "level": "operator", "scopes": ["x", "y"],
                                         "watch_address": "https://example.org/op.pdf"}]
    calls = []

    async def fake_load(db_, source_key, file, title, obtained_from, *rest, version_label=None,
                        max_pages=None, parsed_cache=None, listed_path=None):
        assert listed_path == file.name  # the path as written in corpus.yaml (relative to tmp_path)
        calls.append((source_key, file.name, version_label, max_pages))
        return "promoted", "d"

    counts = await lc.load_all(corpus, tmp_path, db, None, None, None, load=fake_load)

    db.save_levels.assert_called_once_with([
        {"key": "national", "rank": 1, "requires_scope": False},
        {"key": "operator", "rank": 2, "requires_scope": True}])
    db.save_scopes.assert_called_once_with([{"key": "x", "name": "X Netz"}, {"key": "y", "name": "Y Netz"}])
    assert [c.args for c in db.save_source.call_args_list] == [
        ("national-rules", "national", [], None),
        ("op-rules", "operator", ["x", "y"], "https://example.org/op.pdf")]
    assert calls == [("national-rules", "a.pdf", None, None), ("op-rules", "v1.pdf", "V1", None),
                     ("op-rules", "v2.pdf", "V2", 4)]
    assert counts == {"promoted": 3}
    out = capsys.readouterr().out
    assert "added source 'national-rules'" in out
    assert "updated source" not in out  # the stored source already matched


async def test_stored_source_missing_from_corpus_stops_load(tmp_path):
    _files(tmp_path)
    corpus = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    db = _db()
    db.list_source_keys.return_value = ["national-rules", "old-key"]
    load = AsyncMock()

    with pytest.raises(ValueError, match="old-key"):
        await lc.load_all(corpus, tmp_path, db, None, None, None, load=load)
    load.assert_not_awaited()
    db.save_source.assert_not_called()


async def test_source_the_database_refuses_is_reported_and_others_still_load(tmp_path, capsys):
    _files(tmp_path)
    corpus = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    db = _db()
    db.save_source.side_effect = [RuntimeError("source national-rules needs a scope"), None]
    loaded = []

    async def fake_load(db_, source_key, file, *rest, **kwargs):
        loaded.append(file.name)
        return "promoted", "d"

    counts = await lc.load_all(corpus, tmp_path, db, None, None, None, load=fake_load)

    assert loaded == ["v1.pdf", "v2.pdf"]
    assert counts == {"failed": 1, "not attempted": 1, "promoted": 2}
    assert "national-rules: FAILED" in capsys.readouterr().out


async def test_load_all_stops_a_source_after_a_failure(tmp_path):
    _files(tmp_path)
    corpus = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    loaded = []

    async def fake_load(db_, source_key, file, title, obtained_from, *rest, version_label=None,
                        max_pages=None, parsed_cache=None, listed_path=None):
        loaded.append(file.name)
        if file.name == "v1.pdf":
            raise RuntimeError("boom")
        return "promoted", "d"

    counts = await lc.load_all(corpus, tmp_path, _db(), None, None, None, load=fake_load)

    assert loaded == ["a.pdf", "v1.pdf"]  # v2 not loaded over a failed v1
    assert counts == {"promoted": 1, "failed": 1, "not attempted": 1}


ONE_SOURCE = """
sources:
  - {key: a, level: national, versions: [{path: a.pdf, title: A}]}
"""


async def test_load_all_uses_real_load_version_by_default(tmp_path, monkeypatch):
    _pdf(tmp_path / "a.pdf")
    corpus = lc.load_corpus(_corpus(tmp_path, ONE_SOURCE), tmp_path)
    fake = AsyncMock(return_value=("skipped", "d"))
    monkeypatch.setattr(lc, "load_version", fake)
    assert await lc.load_all(corpus, tmp_path, _db(), None, None, None) == {"skipped": 1}
    fake.assert_awaited_once()


async def test_load_all_passes_cache_through(tmp_path):
    _pdf(tmp_path / "a.pdf")
    corpus = lc.load_corpus(_corpus(tmp_path, ONE_SOURCE), tmp_path)
    seen = {}

    async def fake_load(*args, parsed_cache=None, **kwargs):
        seen["cache"] = parsed_cache
        return "promoted", "d"

    await lc.load_all(corpus, tmp_path, _db(), None, None, None, load=fake_load, parsed_cache=tmp_path)
    assert seen["cache"] == tmp_path


async def _noop_load(*a, **k):
    return "skipped", "d"


async def test_load_all_reports_changed_level_scopes_and_address(tmp_path, capsys):
    _files(tmp_path)
    corpus = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    operator_only = dataclasses.replace(corpus, sources=corpus.sources[1:])
    db = _db(key="op-rules", level="national", scopes=["x"], watch_address=None)

    await lc.load_all(operator_only, tmp_path, db, None, None, None, load=_noop_load)

    db.save_source.assert_called_once_with("op-rules", "operator", ["x", "y"], "https://example.org/op.pdf")
    out = capsys.readouterr().out
    assert "updated source 'op-rules'" in out
    assert "level 'national' -> 'operator'" in out
    assert "scopes ['x'] -> ['x', 'y']" in out
    assert "watch address None -> 'https://example.org/op.pdf' (reconfirmed)" in out
