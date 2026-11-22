import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_spec = importlib.util.spec_from_file_location(
    "answers_script", Path(__file__).resolve().parent.parent / "scripts" / "answers.py")
answers = importlib.util.module_from_spec(_spec)
sys.modules["answers_script"] = answers
_spec.loader.exec_module(answers)

ROWS = [
    {"answer_id": "a2", "created_at": "2026-11-20T09:15:00+00:00", "question": "Q2",
     "other_versions": ["bkw-notfallsteuerung (Version: 1.1, Gültig ab: 01.02.2025)"]},
    {"answer_id": "a1", "created_at": "2026-11-01T08:00:00+00:00", "question": "Q1", "other_versions": []},
]


def test_saw_by_source_and_label(capsys):
    db = MagicMock()
    db.find_version.return_value = {"id": "v12"}
    db.answers_that_saw.return_value = ROWS

    assert answers.main(["saw", "--source", "bkw-vorgaben-niederspannung", "--label", "V1.2"], db=db) == 0

    db.find_version.assert_called_once_with("bkw-vorgaben-niederspannung", "V1.2")
    db.answers_that_saw.assert_called_once_with("v12")
    out = capsys.readouterr().out
    assert "2 answers saw this version" in out
    assert "2026-11-20 09:15  Q2" in out
    assert "also saw: bkw-notfallsteuerung (Version: 1.1, Gültig ab: 01.02.2025)" in out
    assert "2026-11-01 08:00  Q1" in out


def test_saw_by_version_id():
    db = MagicMock()
    db.answers_that_saw.return_value = []
    assert answers.main(["saw", "--version", "v12"], db=db) == 0
    db.find_version.assert_not_called()
    db.answers_that_saw.assert_called_once_with("v12")


def test_unknown_version_is_reported(capsys):
    db = MagicMock()
    db.find_version.return_value = None
    assert answers.main(["saw", "--source", "s", "--label", "V9"], db=db) == 2
    assert "no version of s labelled 'V9'" in capsys.readouterr().out


def test_source_needs_label():
    with pytest.raises(SystemExit):
        answers.main(["saw", "--source", "s"], db=MagicMock())
