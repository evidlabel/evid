"""Ligature glyphs the PDF maps to no character (evid.core.pdf_text, quote path, Typst path)."""

from __future__ import annotations

import io

import pymupdf
import pytest
import yaml

from evid.core.pdf_text import (
    LigatureResolver,
    expand_unicode_ligatures,
    has_bad_chars,
    page_text,
)


def _font() -> bytes:
    """A tiny TrueType: f, i, l in the cmap; fi and fl ligatures drawn from them, unmapped;
    and a 'blob' glyph that is no ligature."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    def draw(parts):
        pen = TTGlyphPen(None)
        for x0, y0, x1, y1 in parts:
            pen.moveTo((x0, y0))
            pen.lineTo((x0, y1))
            pen.lineTo((x1, y1))
            pen.lineTo((x1, y0))
            pen.closePath()
        return pen.glyph()

    f = [(60, 0, 140, 700), (140, 620, 300, 700), (20, 400, 240, 470)]
    i = [(60, 0, 140, 480), (60, 560, 140, 650)]
    ell = [(60, 0, 140, 720)]

    def shift(parts, dx):
        return [(a + dx, b, c + dx, d) for a, b, c, d in parts]

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "f", "i", "l", "fi", "fl", "blob"])
    fb.setupCharacterMap({ord("f"): "f", ord("i"): "i", ord("l"): "l"})
    fb.setupGlyf(
        {
            ".notdef": draw([]),
            "f": draw(f),
            "i": draw(i),
            "l": draw(ell),
            "fi": draw(f + shift(i, 320)),
            "fl": draw(f + shift(ell, 320)),
            "blob": draw([(0, -150, 600, -100), (500, 800, 560, 1000)]),
        }
    )
    fb.setupHorizontalMetrics(
        {
            ".notdef": (500, 0),
            "f": (320, 20),
            "i": (200, 60),
            "l": (200, 60),
            "fi": (520, 20),
            "fl": (520, 20),
            "blob": (600, 0),
        }
    )
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Lig Test", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    out = io.BytesIO()
    fb.save(out)
    return out.getvalue()


def make_pdf(path, lines: list[list[int]]) -> None:
    """One text line per entry, each a list of glyph ids (1 f, 2 i, 3 l, 4 fi, 5 fl, 6 blob)."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="F0", fontbuffer=_font())
    for k in range(len(lines)):
        page.insert_text(
            (72, 100 + 40 * k), "i" * len(lines[k]), fontname="F0", fontsize=24
        )
    todo = list(lines)
    for xref in (
        page.get_contents()
    ):  # each insert_text adds a stream; swap its line of i's for the glyphs
        content = doc.xref_stream(xref)
        while todo and (b"<" + b"0002" * len(todo[0]) + b">") in content:
            gids = todo.pop(0)
            content = content.replace(
                b"<" + b"0002" * len(gids) + b">",
                b"<" + "".join(f"{g:04X}" for g in gids).encode() + b">",
                1,
            )
        doc.update_stream(xref, content)
    assert not todo
    doc.save(path)


@pytest.fixture
def lig_pdf(tmp_path):
    p = tmp_path / "lig.pdf"
    make_pdf(p, [[3, 4, 3], [2, 5, 2]])  # "l<fi>l", "i<fl>i"
    return p


def test_unmapped_ligatures_are_expanded(lig_pdf):
    with pymupdf.open(lig_pdf) as pdf:
        page = pdf[0]
        assert has_bad_chars(page.get_text())  # what MuPDF gives: a control character
        text = page_text(page, LigatureResolver(pdf))
    assert text.split() == ["lfil", "ifli"]


def test_same_flags_as_the_typst_path(lig_pdf):
    with pymupdf.open(lig_pdf) as pdf:
        flags = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES
        assert page_text(pdf[0], LigatureResolver(pdf), flags=flags).split() == [
            "lfil",
            "ifli",
        ]


def test_an_unknown_glyph_becomes_fffd_and_is_reported(tmp_path):
    p = tmp_path / "blob.pdf"
    make_pdf(p, [[3, 6, 3]])
    with pymupdf.open(p) as pdf:
        r = LigatureResolver(pdf)
        text = page_text(pdf[0], r)
    assert text.strip() == "l�l"  # never U+0001, never a guess
    assert r.unresolved and r.unresolved[0][2] == 6


def test_clean_pages_are_untouched(tmp_path):
    p = tmp_path / "plain.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Plain text, nothing to fix.\nSecond line.")
    doc.save(p)
    with pymupdf.open(p) as pdf:
        assert page_text(pdf[0], LigatureResolver(pdf)) == pdf[0].get_text()


def test_unicode_ligature_characters():
    assert expand_unicode_ligatures("ﬁnd the ﬂow, oﬀer") == "find the flow, offer"


# ── the quote path ───────────────────────────────────────────────────────────


@pytest.fixture
def doc_dir(tmp_path, lig_pdf):
    d = tmp_path / "docs" / "abcd1234"
    d.mkdir(parents=True)
    lig_pdf.rename(d / "source.pdf")
    (d / "info.yml").write_text(
        yaml.safe_dump(
            {
                "uuid": "abcd1234",
                "title": "Lig test",
                "label": "Lig test",
                "original_name": "source.pdf",
                "authors": "Ann Berg, Carl Dahl, Eva Fisk",
                "dates": "20-02-2018",
            }
        )
    )
    # a rendered memo sorts before the source; the quote path must not read it
    other = pymupdf.open()
    other.new_page().insert_text((72, 100), "a rebuttal, not the source")
    other.save(d / "a_rebut.pdf")
    return d


def test_quotes_get_the_letters_not_a_control_character(doc_dir):
    from evid.core.quote_extract import QuoteCandidate, extract_quotes

    results = extract_quotes(doc_dir, [QuoteCandidate(candidate="lfil")], refresh=True)
    assert results[0].matched and results[0].span["text"] == "lfil"
    text = (doc_dir / "label" / "text.txt").read_text()
    assert "lfil" in text and not has_bad_chars(text) and "rebuttal" not in text


def test_a_frozen_text_with_control_characters_is_extracted_again(doc_dir):
    from evid.core import labels

    labels._write_text(
        doc_dir, "l\x04l\ni\x05i\n", [[0, 1]]
    )  # what an old extractor wrote
    text, _ = labels.ensure_text(doc_dir)
    assert text.split() == ["lfil", "ifli"]
    assert (doc_dir / "label" / "text.txt").read_text() == text


def test_a_quote_over_an_unknown_glyph_is_refused(tmp_path):
    from evid.core.quote_extract import QuoteCandidate, extract_quotes

    d = tmp_path / "docs" / "beef0000"
    d.mkdir(parents=True)
    make_pdf(d / "original.pdf", [[3, 3, 6, 3, 3]])
    (d / "info.yml").write_text(yaml.safe_dump({"uuid": "beef0000", "title": "T"}))
    results = extract_quotes(
        d, [QuoteCandidate(candidate="llXll", min_ratio=0.5)], refresh=True
    )
    assert results[0].matched is False and results[0].span is None


# ── Hayagriva fields ─────────────────────────────────────────────────────────


def test_hayagriva_date():
    from evid.core.hayagriva_fields import hayagriva_date

    assert hayagriva_date("20-02-2018") == "2018-02-20"
    assert hayagriva_date("1.4.2025") == "2025-04-01"
    assert hayagriva_date("2024-06-03") == "2024-06-03"
    assert hayagriva_date("2024") == "2024"
    assert hayagriva_date("21-10-2013, 2014") == "2013-10-21"
    assert hayagriva_date("sometime") is None
    assert hayagriva_date(None) is None


def test_hayagriva_author():
    from evid.core.hayagriva_fields import hayagriva_author

    assert (
        hayagriva_author("Ann Berg, Carl Dahl, Kvinderådet")
        == "Ann Berg and Carl Dahl and Kvinderådet"
    )
    assert hayagriva_author("Ann Berg, Carl Dahl") == "Ann Berg and Carl Dahl"
    assert hayagriva_author("Berg, Ann") == "Berg, Ann"  # one person, Last, First
    assert hayagriva_author("Krisecenter Vejle Ådal") == "Krisecenter Vejle Ådal"
    assert hayagriva_author(["A B", "C D"]) == "A B and C D"
    assert hayagriva_author("") is None


def test_typst_generation_expands_too(tmp_path, lig_pdf):
    from evid.core.typst_generation import textpdf_to_typst

    typ = textpdf_to_typst(lig_pdf)
    assert "lfil" in typ and "ifli" in typ and not has_bad_chars(typ)


def test_second_line_quote(doc_dir):
    from evid.core.quote_extract import QuoteCandidate, extract_quotes

    (r,) = extract_quotes(doc_dir, [QuoteCandidate(candidate="ifli")], refresh=True)
    assert r.key == "abcd:q1" and r.span["text"] == "ifli"
