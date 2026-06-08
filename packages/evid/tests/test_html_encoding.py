"""HTML responses are decoded honouring the real charset (no UTF-8 mojibake)."""

import requests
from evid.core.typst_generation import decoded_response_text
from requests.utils import get_encoding_from_headers

DANISH = (
    "Sagerne omhandler mænd, kvinder og børn. "
    "Den forurettede er ofte en kvinde, og børn indgår i flere sager. "
    "Psykisk vold rammer både mænd og kvinder på tværs af sagerne."
)


def _response(content_bytes: bytes, content_type: str) -> requests.Response:
    r = requests.models.Response()
    r._content = content_bytes
    r.status_code = 200
    r.headers["Content-Type"] = content_type
    r.encoding = get_encoding_from_headers(r.headers)
    return r


def test_utf8_page_without_charset_header_is_decoded():
    # The trap: requests defaults to ISO-8859-1 for text/* with no charset, which
    # would mojibake (mænd -> mÃ¦nd). The helper detects UTF-8 instead.
    r = _response(DANISH.encode("utf-8"), "text/html")
    assert r.encoding == "ISO-8859-1"
    assert r.text != DANISH  # raw .text is corrupted
    assert decoded_response_text(r) == DANISH


def test_declared_utf8_charset_respected():
    r = _response(DANISH.encode("utf-8"), "text/html; charset=utf-8")
    assert decoded_response_text(r) == DANISH


def test_declared_latin1_charset_respected():
    text = "café résumé naïve"
    r = _response(text.encode("latin-1"), "text/html; charset=iso-8859-1")
    assert decoded_response_text(r) == text
