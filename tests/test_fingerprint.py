import hashlib
import unicodedata

from app.ingestion.fingerprint import FINGERPRINT_RULE, file_sha256, text_sha256


def raw(*blocks):
    """Parser output with one chunk holding blocks given as (type, content) pairs."""
    return {"result": {"chunks": [{"blocks": [
        {"type": t, "content": c, "bbox": {"page": 1}} for t, c in blocks]}]}}


BODY = [("Section Header", "4. Steuern oder Sperren"), ("List Item", "Steuerdraht 2 ist optional")]


def test_rule_version_is_positive():
    assert isinstance(FINGERPRINT_RULE, int) and FINGERPRINT_RULE >= 1


def test_heading_change_changes_fingerprint():
    other = [("Section Header", "4. Steuern")] + BODY[1:]
    assert text_sha256(raw(*BODY)) != text_sha256(raw(*other))


def test_short_block_change_changes_fingerprint():
    assert text_sha256(raw(*BODY, ("Text", "16 A"))) != text_sha256(raw(*BODY, ("Text", "20 A")))


def test_footer_page_header_and_figure_ignored():
    noisy = raw(("Header", "BKW Energie AG"), *BODY, ("Footer", "Seite 3 von 9"),
                ("Figure", "Ein Schaltschrank mit Zählern"), ("Page Number", "3"))
    assert text_sha256(noisy) == text_sha256(raw(*BODY))


def test_whitespace_and_unicode_form_ignored():
    nfd = unicodedata.normalize("NFD", "Zähler")
    assert text_sha256(raw(("Text", "Zähler  und\nKlemmen"))) == text_sha256(raw(("Text", f"{nfd} und Klemmen")))


def test_block_order_matters():
    assert text_sha256(raw(*BODY)) != text_sha256(raw(*reversed(BODY)))


def test_blocks_across_chunks_are_read_in_order():
    split = {"result": {"chunks": [{"blocks": [{"type": t, "content": c}]} for t, c in BODY]}}
    assert text_sha256(split) == text_sha256(raw(*BODY))


def test_output_without_blocks_has_a_fingerprint():
    assert text_sha256({"result": {}}) == text_sha256({})


def test_file_fingerprint_is_sha256_of_bytes(tmp_path):
    data = b"%PDF-1.7 example"
    path = tmp_path / "f.pdf"
    path.write_bytes(data)
    assert file_sha256(path) == hashlib.sha256(data).hexdigest()
    assert file_sha256(str(path)) == hashlib.sha256(data).hexdigest()
