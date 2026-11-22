"""Helpers of scripts/experiments/version_baseline.py (stale case after the versioned store)."""
import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "version_baseline",
    Path(__file__).resolve().parent.parent / "scripts" / "experiments" / "version_baseline.py",
)
vb = importlib.util.module_from_spec(_spec)
sys.modules["version_baseline"] = vb
_spec.loader.exec_module(vb)


def _c(doc, sim, cid=None):
    return {"id": cid or f"{doc}-{sim}", "version_id": doc, "similarity": sim}


def test_cosine():
    assert vb.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert vb.cosine([1.0, 0.0], [0.0, 2.0]) == pytest.approx(0.0)
    assert vb.cosine([1.0, 1.0], [2.0, 2.0]) == pytest.approx(1.0)


def test_stale_candidates_equal_top_k_of_union_without_dropped_version():
    live = [_c("v13", 0.95), _c("other", 0.9), _c("v13", 0.85), _c("other", 0.6)]
    scratch = [_c("v12", 0.92), _c("v12", 0.5)]
    # union top-4: v13 .95, v12 .92, other .9, v13 .85 -> drop v13
    result = vb.stale_candidates(live, scratch, drop_version_id="v13", k=4)
    assert [(c["version_id"], c["similarity"]) for c in result] == [("v12", 0.92), ("other", 0.9)]


def test_stale_candidates_keeps_similarity_order_and_k():
    live = [_c("other", s / 10) for s in range(9, 0, -1)]
    scratch = [_c("v12", 0.95), _c("v12", 0.05)]
    result = vb.stale_candidates(live, scratch, drop_version_id="v13", k=5)
    sims = [c["similarity"] for c in result]
    assert sims == sorted(sims, reverse=True)
    assert len(result) == 5
    assert result[0]["version_id"] == "v12"


def test_scratch_chunks_carry_version_and_source_fields():
    class Chunk:
        def __init__(self, i):
            self.content, self.section_title, self.page_number = f"text {i}", "S", 1
            self.chunk_index, self.token_count = i, 3

    version = {"id": "v12", "title": "Doc", "version_label": "V1.2"}
    source_fields = {"source_key": "s", "level": "operator", "rank": 2, "scopes": ["bkw"]}
    out = vb.scratch_chunks([Chunk(0), Chunk(1)], [[1.0, 0.0], [0.0, 1.0]], [1.0, 0.0], version, source_fields)
    assert [c["similarity"] for c in out] == pytest.approx([1.0, 0.0])
    assert out[0]["version_id"] == "v12"
    assert (out[0]["version_title"], out[0]["version_label"]) == ("Doc", "V1.2")
    assert out[0]["scopes"] == ["bkw"]
    assert out[0]["id"] == "scratch-v12-0"


def test_modes():
    assert set(vb.MODES) == {"current", "stale"}


def test_pick_versions_finds_the_pair_by_label():
    rows = [
        {"id": "a", "source_key": vb.SOURCE_KEY, "version_label": "V1.2"},
        {"id": "b", "source_key": "bkw-vorgaben-niederspannung", "version_label": "V1.3"},
        {"id": "c", "source_key": "other", "version_label": "V1.2"},
    ]
    v12, v13 = vb.pick_versions(rows, "V1.2", "V1.3")
    assert vb.SOURCE_KEY == "bkw-vorgaben-niederspannung"
    assert (v12["id"], v13["id"]) == ("a", "b")
