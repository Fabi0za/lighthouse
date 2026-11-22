import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("load_eval_questions", ROOT / "scripts" / "load_eval_questions.py")
leq = importlib.util.module_from_spec(_spec)
sys.modules["load_eval_questions"] = leq
_spec.loader.exec_module(leq)

GOOD = """
questions:
  - key: bkw-steuerdraht-2-doppeltarif
    question: "Muss ein Steuerdraht 2 vorgesehen werden?"
    question_type: answerable
    case_type: changed_between_versions
    expected_answer: "Nein."
    sources:
      - {source_key: bkw-vorgaben-niederspannung, version_label: "Version: V1.3, Gültig ab 21.05.2025"}
    facts:
      - "Auf das Vorbereiten des Doppeltarif-Drahts (Nr. 2) kann verzichtet werden."
"""


def _file(tmp_path, body):
    f = tmp_path / "questions.yaml"
    f.write_text(body, encoding="utf-8")
    return f


def _db(version=None):
    db = MagicMock()
    db.find_version.return_value = {"text_sha256": "t13"} if version is None else version
    return db


def test_label_resolved_to_fingerprint(tmp_path, capsys):
    db = _db()
    assert leq.main(["--file", str(_file(tmp_path, GOOD))], db=db) == 0
    db.find_version.assert_called_once_with("bkw-vorgaben-niederspannung", "Version: V1.3, Gültig ab 21.05.2025")
    (question,) = [c.args[0] for c in db.save_eval_question.call_args_list]
    assert question["sources"] == [{"source_key": "bkw-vorgaben-niederspannung", "written_from_text_sha256": "t13"}]
    assert question["facts"] == ["Auf das Vorbereiten des Doppeltarif-Drahts (Nr. 2) kann verzichtet werden."]
    assert "saved 1 eval questions" in capsys.readouterr().out


def test_unknown_source_or_label_reported_by_question_key(tmp_path, capsys):
    db = _db(version=False)
    db.find_version.return_value = None
    assert leq.main(["--file", str(_file(tmp_path, GOOD))], db=db) == 2
    out = capsys.readouterr().out
    assert "bkw-steuerdraht-2-doppeltarif: no version of bkw-vorgaben-niederspannung labelled" in out
    db.save_eval_question.assert_not_called()


def test_bad_fields_reported_before_anything_is_written(tmp_path, capsys):
    body = GOOD.replace("case_type: changed_between_versions", "case_type: Verkabelung") \
               .replace("key: bkw-steuerdraht-2-doppeltarif", "key: Bad Key")
    db = _db()
    assert leq.main(["--file", str(_file(tmp_path, body))], db=db) == 2
    out = capsys.readouterr().out
    assert "Bad Key: key must be lowercase letters and digits joined by hyphens" in out
    assert "case_type must be one of" in out
    db.save_eval_question.assert_not_called()


def test_missing_file_message(tmp_path, capsys):
    assert leq.main(["--file", str(tmp_path / "none.yaml")], db=_db()) == 2
    assert "no eval question file" in capsys.readouterr().out


def test_repo_question_file_is_valid():
    data = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text(encoding="utf-8"))
    questions = data["questions"]
    assert len(questions) == 2
    for q in questions:
        assert leq.KEY_FORMAT.match(q["key"])
        assert q["case_type"] == "changed_between_versions"
        assert q["sources"] == [{"source_key": "bkw-vorgaben-niederspannung",
                                 "version_label": "Version: V1.3, Gültig ab 21.05.2025"}]
        assert q["facts"] and all(isinstance(f, str) for f in q["facts"])
