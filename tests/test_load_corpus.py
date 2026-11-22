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


def _pdf(path: Path, pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200 + pages)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _corpus(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "corpus.yaml"
    p.write_text(body, encoding="utf-8")
    return p


GOOD = """
sources:
  - title: National rules
    issuer: VSE
    level: national
    versions:
      - {path: a.pdf, title: "National rules 2025", address: "https://example.org/a.pdf"}
  - title: Operator rules
    issuer: Op
    level: operator
    scopes: [X, Y]
    listing_address: "https://example.org/list"
    versions:
      - {path: v1.pdf, title: "Operator rules (V1)"}
      - {path: v2.pdf, title: "Operator rules (V2)", max_pages: 4}
"""


def _files(tmp_path):
    _pdf(tmp_path / "a.pdf", 1)
    _pdf(tmp_path / "v1.pdf", 2)
    _pdf(tmp_path / "v2.pdf", 3)


def test_load_corpus_reads_sources_and_versions(tmp_path):
    _files(tmp_path)
    national, operator = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    assert (national.level, national.scopes) == ("national", [])
    assert not hasattr(national, "authority_rank")
    assert national.versions[0].address == "https://example.org/a.pdf"
    assert operator.scopes == ["X", "Y"]
    assert operator.listing_address == "https://example.org/list"
    assert [v.path for v in operator.versions] == ["v1.pdf", "v2.pdf"]
    assert operator.versions[1].max_pages == 4
    assert operator.versions[0].address is None


def test_load_corpus_reports_all_problems(tmp_path):
    _pdf(tmp_path / "a.pdf")
    corpus = _corpus(tmp_path, """
sources:
  - {title: A, issuer: VSE, level: regional, versions: [{path: a.pdf, title: A}]}
  - {title: B, issuer: X, level: operator, versions: [{path: a.pdf, title: B}]}
  - {title: C, issuer: X, level: national, versions: [{path: missing.pdf, title: C}]}
  - {issuer: X, level: national, versions: [{path: a.pdf, title: D}]}
  - {title: E, issuer: X, level: national, versions: []}
  - {title: F, issuer: X, level: national, versions: [{path: a.pdf, title: F, max_pages: 0}]}
""")
    with pytest.raises(ValueError) as e:
        lc.load_corpus(corpus, tmp_path)
    msg = str(e.value)
    assert "level must be one of" in msg
    assert "operator sources need scopes" in msg
    assert "missing.pdf: file not found" in msg
    assert "missing title" in msg
    assert "E: no versions" in msg
    assert "max_pages must be a positive integer" in msg


def test_load_corpus_rejects_duplicate_source_titles(tmp_path):
    _pdf(tmp_path / "a.pdf")
    _pdf(tmp_path / "b.pdf", 2)
    corpus = _corpus(tmp_path, """
sources:
  - {title: Same, issuer: X, level: national, versions: [{path: a.pdf, title: A}]}
  - {title: Same, issuer: X, level: national, versions: [{path: b.pdf, title: B}]}
""")
    with pytest.raises(ValueError, match="source title listed twice"):
        lc.load_corpus(corpus, tmp_path)


def test_load_corpus_rejects_path_listed_twice(tmp_path):
    _pdf(tmp_path / "a.pdf")
    corpus = _corpus(tmp_path, """
sources:
  - {title: A, issuer: X, level: national, versions: [{path: a.pdf, title: A}, {path: a.pdf, title: A2}]}
""")
    with pytest.raises(ValueError, match="listed twice"):
        lc.load_corpus(corpus, tmp_path)


def test_plan_skips_stored_files_and_says_cache_or_parse(tmp_path):
    _files(tmp_path)
    sources = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    known = {file_sha256(tmp_path / "v1.pdf")}
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{file_sha256(tmp_path / 'v2.pdf')}.json").write_text("{}", encoding="utf-8")
    actions = {v.path: a for _, v, a in lc.plan(sources, known, tmp_path, parsed_cache=cache)}
    assert actions == {"a.pdf": "parse", "v1.pdf": "skip", "v2.pdf": "cache"}


def test_plan_without_cache_parses(tmp_path):
    _files(tmp_path)
    sources = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    actions = {v.path: a for _, v, a in lc.plan(sources, set(), tmp_path)}
    assert set(actions.values()) == {"parse"}


def test_repo_corpus_is_valid():
    """The checked-in corpus.yaml parses and lists BKW Vorgaben V1.2 before V1.3."""
    root = Path(__file__).resolve().parent.parent
    data = __import__("yaml").safe_load((root / "corpus.yaml").read_text(encoding="utf-8"))
    vorgaben = [s for s in data["sources"] if "Vorgaben an Niederspannungs" in s["title"]]
    assert len(vorgaben) == 1
    paths = [v["path"] for v in vorgaben[0]["versions"]]
    assert paths == ["data/BKW/DE_Vorgaben_BKW_V1.2.pdf", "data/BKW/20250521_DE_Vorgaben_BKW_V1.3.pdf"]
    assert all(s.get("scopes") for s in data["sources"] if s["level"] == "operator")


async def test_load_all_creates_source_once_and_loads_versions_in_order(tmp_path):
    _files(tmp_path)
    sources = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    db = MagicMock()
    db.find_source.side_effect = [None, {"id": "existing", "issuer": "Op", "level": "operator",
                                         "listing_address": "https://example.org/list"}]
    db.get_scopes.return_value = ["X", "Y"]
    db.insert_source.return_value = {"id": "new-src"}
    calls = []

    async def fake_load(db_, source, file, title, address, *rest, max_pages=None, stored_path=None,
                        parsed_cache=None):
        calls.append((source["id"], stored_path, max_pages))
        return "promoted", "d"

    counts = await lc.load_all(sources, tmp_path, db, None, None, None, load=fake_load)

    db.insert_source.assert_called_once_with("National rules", "VSE", "national", [], None, None)
    assert calls == [("new-src", "a.pdf", None), ("existing", "v1.pdf", None), ("existing", "v2.pdf", 4)]
    assert counts == {"promoted": 3}
    db.update_source.assert_not_called()  # stored source already matches corpus.yaml
    db.set_scopes.assert_not_called()


async def test_load_all_stops_a_source_after_a_failure(tmp_path):
    _files(tmp_path)
    sources = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)
    db = MagicMock()
    db.find_source.return_value = {"id": "s"}
    loaded = []

    async def fake_load(db_, source, file, title, address, *rest, max_pages=None, stored_path=None,
                        parsed_cache=None):
        loaded.append(stored_path)
        if stored_path == "v1.pdf":
            raise RuntimeError("boom")
        return "promoted", "d"

    counts = await lc.load_all(sources, tmp_path, db, None, None, None, load=fake_load)

    assert loaded == ["a.pdf", "v1.pdf"]  # v2 not loaded over a failed v1
    assert counts == {"promoted": 1, "failed": 1, "not attempted": 1}


async def test_load_all_uses_real_load_version_by_default(tmp_path, monkeypatch):
    _pdf(tmp_path / "a.pdf")
    sources = lc.load_corpus(_corpus(tmp_path, """
sources:
  - {title: A, issuer: X, level: national, versions: [{path: a.pdf, title: A}]}
"""), tmp_path)
    fake = AsyncMock(return_value=("skipped", "d"))
    monkeypatch.setattr(lc, "load_version", fake)
    db = MagicMock()
    db.find_source.return_value = {"id": "s"}
    assert await lc.load_all(sources, tmp_path, db, None, None, None) == {"skipped": 1}
    fake.assert_awaited_once()


async def test_load_all_passes_cache_through(tmp_path):
    _pdf(tmp_path / "a.pdf")
    sources = lc.load_corpus(_corpus(tmp_path, """
sources:
  - {title: A, issuer: X, level: national, versions: [{path: a.pdf, title: A}]}
"""), tmp_path)
    seen = {}

    async def fake_load(*args, parsed_cache=None, **kwargs):
        seen["cache"] = parsed_cache
        return "promoted", "d"

    db = MagicMock()
    db.find_source.return_value = {"id": "s"}
    await lc.load_all(sources, tmp_path, db, None, None, None, load=fake_load, parsed_cache=tmp_path)
    assert seen["cache"] == tmp_path


def _stored(**over):
    row = {"id": "s", "issuer": "Op", "level": "operator",
           "listing_address": "https://example.org/list"}
    return {**row, **over}


async def _noop_load(*a, **k):
    return "skipped", "d"


async def test_load_all_syncs_changed_source_fields_and_scopes(tmp_path, capsys):
    _files(tmp_path)
    sources = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)[1:]  # the operator source
    db = MagicMock()
    db.find_source.return_value = _stored(issuer="Old issuer", level="national")
    db.get_scopes.return_value = ["X"]

    await lc.load_all(sources, tmp_path, db, None, None, None, load=_noop_load)

    db.update_source.assert_called_once_with(
        "s", {"issuer": "Op", "level": "operator"})
    db.set_scopes.assert_called_once_with("s", ["X", "Y"])
    out = capsys.readouterr().out
    assert "updated source 'Operator rules'" in out
    assert "scopes ['X'] -> ['X', 'Y']" in out


async def test_load_all_leaves_matching_source_alone(tmp_path):
    _files(tmp_path)
    sources = lc.load_corpus(_corpus(tmp_path, GOOD), tmp_path)[1:]
    db = MagicMock()
    db.find_source.return_value = _stored()
    db.get_scopes.return_value = ["Y", "X"]  # order does not matter

    await lc.load_all(sources, tmp_path, db, None, None, None, load=_noop_load)

    db.update_source.assert_not_called()
    db.set_scopes.assert_not_called()
