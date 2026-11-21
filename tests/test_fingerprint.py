import hashlib
import unicodedata

from app.ingestion.fingerprint import file_sha256, text_sha256


def test_whitespace_runs_do_not_change_text_fingerprint():
    assert text_sha256([{"content": "a  b\n"}]) == text_sha256([{"content": "a b"}])


def test_changed_word_changes_text_fingerprint():
    assert text_sha256([{"content": "a b"}]) != text_sha256([{"content": "a c"}])


def test_section_order_matters():
    one, two = {"content": "first"}, {"content": "second"}
    assert text_sha256([one, two]) != text_sha256([two, one])


def test_unicode_normal_forms_hash_equal():
    nfc = unicodedata.normalize("NFC", "ä")
    nfd = unicodedata.normalize("NFD", "ä")
    assert nfc != nfd
    assert text_sha256([{"content": nfc}]) == text_sha256([{"content": nfd}])


def test_file_fingerprint_is_sha256_of_bytes(tmp_path):
    data = b"%PDF-1.7 example"
    path = tmp_path / "f.pdf"
    path.write_bytes(data)
    assert file_sha256(path) == hashlib.sha256(data).hexdigest()
    assert file_sha256(str(path)) == hashlib.sha256(data).hexdigest()
