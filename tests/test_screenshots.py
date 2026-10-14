"""Screenshot ingest: page images become one OCR'd PDF."""

from __future__ import annotations

import hashlib
import json
import logging

import pymupdf
import pytest

from evid.cli.evidence import add_screenshots
from evid.core.pdf_text import page_text
from evid.services import screenshots as shots
from evid.services.layout import find_set_dir


def _png(path, width: int, height: int = 20):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), 0)
    pix.clear_with(255)
    pix.save(str(path))
    return path


def _stub_ocr(pix, _lang: str) -> bytes:
    """A one-page PDF whose text names the pixmap width. No Tesseract."""
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=80)
    page.insert_text((20, 40), f"page-text {pix.width}")
    raw = doc.tobytes(garbage=4, deflate=True, no_new_id=True, reproducible=True)
    doc.close()
    return raw


def test_directory_is_natural_order_and_one_name(tmp_path, caplog):
    folder = tmp_path / "issuu"
    folder.mkdir()
    _png(folder / "page10.png", 10)
    _png(folder / "page2.png", 20)
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        shot = shots.collect_images([str(folder)])
    assert [p.name for p in shot.images] == ["page2.png", "page10.png"]
    assert shot.title == "issuu"
    assert shot.source_name == "issuu.pdf"
    assert "not images" in caplog.text


def test_several_files_keep_argument_order(tmp_path):
    a = _png(tmp_path / "b.png", 10)
    b = _png(tmp_path / "a.png", 12)
    shot = shots.collect_images([str(a), str(b)])
    assert [p.name for p in shot.images] == ["b.png", "a.png"]
    assert shot.source_name == "screenshots.pdf"
    assert shot.title == "b"


def test_rejects_a_non_image_and_an_empty_directory(tmp_path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="image"):
        shots.collect_images([str(tmp_path / "notes.txt")])
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="No screenshots"):
        shots.collect_images([str(empty)])
    with pytest.raises(FileNotFoundError):
        shots.collect_images([str(tmp_path / "missing.png")])


def test_fit_page_shrinks_a_wide_screenshot():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2000, 1000), 0)
    pix.set_dpi(96, 96)
    shots._fit_page(pix)
    long_pt = max(pix.width, pix.height) * 72 / pix.xres
    assert long_pt <= shots._LONG_PT + 1
    assert pix.width == 2000  # dpi changes, pixels do not


def test_two_builds_of_the_same_pages_match(tmp_path, monkeypatch):
    monkeypatch.setattr(shots, "ocr_pixmap", _stub_ocr)
    a = _png(tmp_path / "a.png", 30)
    b = _png(tmp_path / "b.png", 80)
    first = tmp_path / "one.pdf"
    second = tmp_path / "two.pdf"
    shots.screenshots_to_pdf([a, b], first)
    shots.screenshots_to_pdf([a, b], second)
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    )
    with pymupdf.open(first) as doc:
        assert doc.page_count == 2
        assert "page-text 30" in doc[0].get_text()
        assert "page-text 80" in doc[1].get_text()


def test_ingest_writes_text_and_the_ocr_note(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(shots, "ocr_pixmap", _stub_ocr)
    a = _png(tmp_path / "a.png", 30)
    b = _png(tmp_path / "b.png", 80)
    db = tmp_path / "db"
    add_screenshots(
        db,
        "case",
        [str(a), str(b)],
        title="Issuu report",
        url="https://issuu.com/example/docs/report",
        no_index=True,
    )
    docs = list((find_set_dir(db, "case") / "docs").iterdir())
    assert len(docs) == 1
    text = (docs[0] / "label" / "text.txt").read_text(encoding="utf-8")
    assert "page-text 30" in text and "page-text 80" in text
    labels = json.loads((docs[0] / "label" / "labels.json").read_text(encoding="utf-8"))
    notes = labels["document"][0]["notes"]
    assert notes[0]["text"] == shots.SCREENSHOT_NOTE
    assert notes[0]["by"] == "evid"
    info = (docs[0] / "info.yml").read_text(encoding="utf-8")
    assert "Issuu report" in info
    assert "https://issuu.com/example/docs/report" in info
    assert "screenshots.pdf" in info

    add_screenshots(db, "case", [str(a), str(b)], no_index=True)
    labels = json.loads((docs[0] / "label" / "labels.json").read_text(encoding="utf-8"))
    assert len(labels["document"]) == 1
    assert "already added" in capsys.readouterr().out


def _ocr_ready() -> bool:
    try:
        shots.require_ocr("dan+eng")
    except ValueError:
        return False
    return True


@pytest.mark.skipif(not _ocr_ready(), reason="tesseract dan+eng not installed")
def test_real_ocr_reads_the_words(tmp_path):
    src = pymupdf.open()
    page = src.new_page(width=500, height=160)
    page.insert_text((36, 90), "Kendelser fra Ankestyrelsen", fontsize=22)
    pix = page.get_pixmap(dpi=200)
    png = tmp_path / "page.png"
    pix.save(str(png))
    src.close()
    out = tmp_path / "out.pdf"
    shots.screenshots_to_pdf([png], out, lang="dan+eng")
    with pymupdf.open(out) as doc:
        assert "Ankestyrelsen" in doc[0].get_text()


def test_missing_ocr_language_explains_itself():
    with pytest.raises(ValueError, match="Tesseract"):
        shots.require_ocr("zz")


def _pdf(draw, width=500, height=280) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    draw(page)
    raw = doc.tobytes()
    doc.close()
    return raw


def _lines(raw) -> list[str]:
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        return [line.strip() for line in doc[0].get_text().splitlines() if line.strip()]


def _put(page, x, y, text, size=12):
    page.insert_text((x, y), text, fontsize=size, fontname="helv")


def test_multicolumn_reads_down_each_column():
    left = [
        "København finder sagen.",
        "Alpha continues the argument.",
        "Alpha closes the left column.",
    ]
    right = [
        "Beta states a separate point.",
        "Beta adds the second column.",
        "Beta ends on the right.",
    ]

    def draw(page):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), 0)
        pix.clear_with(0)
        page.insert_image(pymupdf.Rect(4, 4, 24, 24), pixmap=pix)
        _put(page, 36, 24, "The report title spans the page")
        for i, (a, b) in enumerate(zip(left, right, strict=True)):
            _put(page, 36, 50 + i * 20, a)
            _put(page, 270, 50 + i * 20, b)
        _put(page, 36, 250, "Footer note across the bottom")

    raw = _pdf(draw)
    fixed = shots._reading_order(raw)
    again = shots._reading_order(raw)
    assert fixed == again
    assert _lines(fixed) == [
        "The report title spans the page",
        "København finder sagen.",
        "Alpha continues the argument.",
        "Alpha closes the left column.",
        "Beta states a separate point.",
        "Beta adds the second column.",
        "Beta ends on the right.",
        "Footer note across the bottom",
    ]
    with pymupdf.open(stream=fixed, filetype="pdf") as doc:
        body = page_text(doc[0])
        assert doc[0].get_images()
        pix = doc[0].get_pixmap(dpi=20)
    assert "København finder sagen." in body
    assert body.index("closes the left") < body.index("Beta states")
    assert any(sample < 250 for sample in pix.samples)


def test_a_shared_baseline_splits_into_columns():
    """One text line with a wide middle gap, the way a single OCR line looks."""
    left = [
        "Alpha finds the first fact.",
        "Alpha continues the argument.",
        "Alpha closes the left column.",
    ]
    right = [
        "Beta states a separate point.",
        "Beta adds the second column.",
        "Beta ends on the right.",
    ]

    def draw(page):
        for i, (a, b) in enumerate(zip(left, right, strict=True)):
            _put(page, 36, 40 + i * 20, a + " " * 18 + b)

    fixed = shots._reading_order(_pdf(draw, height=160))
    assert _lines(fixed) == [
        *left,
        *right,
    ]


def test_the_longer_column_stays_together():
    def draw(page):
        _put(page, 36, 30, "Heading", size=16)
        left = [
            "Left one is long enough.",
            "Left two continues here.",
            "Left three stays left.",
            "Left four extra line.",
        ]
        right = ["Right one is here.", "Right two only now."]
        for i, line in enumerate(right):
            _put(page, 36, 60 + i * 18, left[i])
            _put(page, 280, 60 + i * 18, line)
        _put(page, 36, 60 + 2 * 18, left[2])
        _put(page, 36, 60 + 3 * 18, left[3])
        _put(page, 36, 200, "Footer under both.")

    fixed = shots._reading_order(_pdf(draw, height=240))
    assert _lines(fixed) == [
        "Heading",
        "Left one is long enough.",
        "Left two continues here.",
        "Left three stays left.",
        "Left four extra line.",
        "Right one is here.",
        "Right two only now.",
        "Footer under both.",
    ]


def test_single_column_ocr_bytes_stay():
    def draw(page):
        for i, line in enumerate(
            ["Only one column here.", "Second line of it.", "Third line stays put."]
        ):
            _put(page, 36, 40 + i * 18, line)

    raw = _pdf(draw, width=400, height=160)
    assert shots._reading_order(raw) is raw


def test_a_wide_gap_on_one_line_is_not_a_column():
    def draw(page):
        _put(page, 36, 40, "Short")
        _put(page, 220, 40, "words far apart")
        _put(page, 36, 70, "Another ordinary line of text here.")
        _put(page, 36, 100, "And a third line.")

    raw = _pdf(draw, width=400, height=160)
    assert shots._reading_order(raw) is raw


def test_a_short_cell_table_stays_in_row_order():
    def draw(page):
        rows = [
            ("Name", "Age", "City"),
            ("Ada", "31", "York"),
            ("Ben", "42", "Oslo"),
            ("Cia", "7", "Rome"),
        ]
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                _put(page, 40 + j * 140, 40 + i * 28, cell, size=14)

    raw = _pdf(draw, height=200)
    assert shots._reading_order(raw) is raw
    assert _lines(raw)[:3] == ["Name", "Age", "City"]


def test_text_already_in_column_order_is_unchanged():
    def draw(page):
        for i, line in enumerate(
            [
                "Alpha finds the first fact.",
                "Alpha continues the argument.",
                "Alpha closes the left column.",
            ]
        ):
            _put(page, 36, 40 + i * 20, line)
        for i, line in enumerate(
            [
                "Beta states a separate point.",
                "Beta adds the second column.",
                "Beta ends on the right.",
            ]
        ):
            _put(page, 270, 40 + i * 20, line)

    raw = _pdf(draw, height=160)
    assert shots._reading_order(raw) is raw


def test_unreadable_ocr_bytes_are_kept():
    blob = b"not a pdf"
    assert shots._reading_order(blob) is blob


def test_ocr_pixmap_reorders_a_multicolumn_page(monkeypatch):
    def draw(page):
        for i, (a, b) in enumerate(
            zip(
                ["Alpha finds the first fact.", "Alpha continues the argument."],
                ["Beta states a separate point.", "Beta adds the second column."],
                strict=True,
            )
        ):
            _put(page, 36, 40 + i * 20, a)
            _put(page, 270, 40 + i * 20, b)

    raw = _pdf(draw, height=120)

    class _Pix:
        def pdfocr_tobytes(self, compress, language):
            assert compress is True
            assert language == "dan+eng"
            return raw

    monkeypatch.setattr(shots, "require_ocr", lambda _lang: "/tmp")
    fixed = shots.ocr_pixmap(_Pix(), "dan+eng")
    assert _lines(fixed) == [
        "Alpha finds the first fact.",
        "Alpha continues the argument.",
        "Beta states a separate point.",
        "Beta adds the second column.",
    ]


@pytest.mark.skipif(not _ocr_ready(), reason="tesseract dan+eng not installed")
def test_real_ocr_reads_columns_down(tmp_path):
    src = pymupdf.open()
    page = src.new_page(width=500, height=280)
    _put(page, 36, 24, "The report title spans the page")
    left = [
        "Alpha finds the first fact.",
        "Alpha continues the argument.",
        "Alpha closes the left column.",
    ]
    right = [
        "Beta states a separate point.",
        "Beta adds the second column.",
        "Beta ends on the right.",
    ]
    for i, (a, b) in enumerate(zip(left, right, strict=True)):
        _put(page, 36, 50 + i * 20, a)
        _put(page, 270, 50 + i * 20, b)
    _put(page, 36, 240, "Footer note across the bottom")
    png = tmp_path / "page.png"
    page.get_pixmap(dpi=160, alpha=False).save(str(png))
    src.close()
    first = tmp_path / "one.pdf"
    second = tmp_path / "two.pdf"
    shots.screenshots_to_pdf([png], first, lang="eng")
    shots.screenshots_to_pdf([png], second, lang="eng")
    assert first.read_bytes() == second.read_bytes()
    with pymupdf.open(first) as doc:
        text = page_text(doc[0])
        assert doc[0].get_images()
    assert text.index("title") < text.index("Alpha finds")
    assert text.index("closes the left") < text.index("Beta states")
    assert text.index("ends on the right") < text.index("Footer")
