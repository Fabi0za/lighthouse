import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_spec = importlib.util.spec_from_file_location(
    "flags_script", Path(__file__).resolve().parent.parent / "scripts" / "flags.py")
flags = importlib.util.module_from_spec(_spec)
sys.modules["flags_script"] = flags
_spec.loader.exec_module(flags)

SETTINGS = SimpleNamespace(confirmation_max_age_days=180)


def run(argv, db):
    return flags.main(argv, db=db, settings=SETTINGS)


def test_list_prints_one_line_per_open_flag(capsys):
    db = MagicMock()
    db.list_open_flags.return_value = [
        {"id": 12, "source_key": "bkw-vorgaben-niederspannung", "kind": "candidate",
         "reason": "possible_successor", "detail": {"address": "https://example.org/v2.pdf", "message": "evidence"},
         "versions": [{"id": "v2"}]},
        {"id": 13, "source_key": "ekz-wv-spezielle-bestimmungen", "kind": "check_failed",
         "reason": "load_failed", "detail": {"file": "data/EKZ/wv.pdf"}, "versions": []},
    ]
    assert run(["list"], db) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "#12 bkw-vorgaben-niederspannung candidate/possible_successor https://example.org/v2.pdf: evidence "
        "(version v2)",
        "#13 ekz-wv-spezielle-bestimmungen check_failed/load_failed data/EKZ/wv.pdf",
    ]


def test_list_says_when_nothing_is_open(capsys):
    db = MagicMock()
    db.list_open_flags.return_value = []
    run(["list"], db)
    assert capsys.readouterr().out.strip() == "no open flags"


def test_approve_prints_answers_that_saw_the_retired_version(capsys):
    db = MagicMock()
    db.approve_candidate.return_value = 4
    assert run(["approve", "v2"], db) == 0
    db.approve_candidate.assert_called_once_with("v2")
    assert "the version it retired was seen by 4 earlier answers" in capsys.readouterr().out


def test_reject_and_confirm():
    db = MagicMock()
    run(["reject", "v2"], db)
    run(["confirm", "bkw-vorgaben-niederspannung"], db)
    db.reject_version.assert_called_once_with("v2")
    db.confirm_source.assert_called_once_with("bkw-vorgaben-niederspannung")


def test_raise_overdue_uses_setting_or_override(capsys):
    db = MagicMock()
    db.raise_overdue_flags.return_value = 2
    run(["raise-overdue"], db)
    run(["raise-overdue", "--max-age-days", "30"], db)
    assert [c.args for c in db.raise_overdue_flags.call_args_list] == [(180,), (30,)]
    assert "2 overdue flags raised (older than 180 days)" in capsys.readouterr().out


def test_report_unreachable():
    db = MagicMock()
    db.raise_check_failed.return_value = 14
    run(["report-unreachable", "bkw-notfallsteuerung", "https://example.org/gone.pdf", "--message", "HTTP 404"], db)
    db.raise_check_failed.assert_called_once_with("bkw-notfallsteuerung", "https://example.org/gone.pdf", "HTTP 404")


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit):
        run(["delete", "12"], MagicMock())
