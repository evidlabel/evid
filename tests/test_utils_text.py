from evid.utils.text import normalize_text


def test_normalize_text_str():
    assert normalize_text("  test æøå  ") == "test æøå"


def test_normalize_text_bytes():
    assert normalize_text(b"  test \xc3\xa6\xc3\xb8\xc3\xa5  ") == "test æøå"


def test_normalize_text_none():
    assert normalize_text(None, "default") == "default"


def test_normalize_text_latin1():
    assert normalize_text(b"\xe6\xf8\xe5") == "æøå"
