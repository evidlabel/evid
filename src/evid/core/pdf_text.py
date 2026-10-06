"""Page text from a PDF, with ligatures expanded to the letters they draw.

Some PDFs draw ligatures (fi, fl, ff, …) with glyphs whose ToUnicode entry is
U+FFFD, so MuPDF reports U+0001 (ligatures preserved) or U+FFFD (not) for them.
Neither is the text on the page, and U+0001 is illegal in YAML, so a quote that
contains it breaks Hayagriva and Typst.

:func:`page_text` is the one place PDF page text is read (the quote path and the
Typst generator both use it):

- pages without such characters come back exactly as ``page.get_text()`` gives
  them, so character offsets of existing quotes do not move;
- each unmapped glyph is identified by ``(font, glyph id)`` from
  ``get_texttrace`` and expanded by comparing its outline with the outlines of
  candidate letter sequences (fi, fl, ff, ffi, …) drawn from the same typeface —
  the glyph itself or a sibling subset of it in the same PDF. Only a clear match
  is accepted;
- Unicode ligature characters (U+FB00 to U+FB06) expand through ``LIGATURES``;
- a glyph that cannot be identified becomes U+FFFD (never U+0001) and is logged
  with its font, glyph id and page, so a quote over it can be refused.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any

from evid.core.text_cleaning import LIGATURES

logger = logging.getLogger(__name__)

REPLACEMENT = "�"
CANDIDATES = (
    "ff",
    "fi",
    "fl",
    "ffi",
    "ffl",
    "ft",
    "fj",
    "fb",
    "fh",
    "fk",
    "f",
    "st",
    "tt",
    "Th",
)
MIN_SCORE = 0.92  # outline overlap (IoU) the best candidate needs
MIN_MARGIN = 0.05  # and its lead over the runner-up


def is_bad_char(c: str) -> bool:
    """A character that is not text: U+FFFD, or a C0 control other than tab / LF / CR."""
    return c == REPLACEMENT or (ord(c) < 32 and c not in "\t\n\r")


def has_bad_chars(text: str) -> bool:
    return any(is_bad_char(c) for c in text)


def expand_unicode_ligatures(text: str) -> str:
    for lig, letters in LIGATURES.items():
        if lig in text:
            text = text.replace(lig, letters)
    return text


# ── glyph outlines ────────────────────────────────────────────────────────────


def _flat_pen(glyph_set):
    from fontTools.pens.basePen import BasePen

    class FlatPen(BasePen):
        """Outline as polygons (curves flattened)."""

        steps = 8

        def __init__(self, gs):
            super().__init__(gs)
            self.polys: list[list[tuple[float, float]]] = []

        def _moveTo(self, p):
            self.polys.append([p])

        def _lineTo(self, p):
            self.polys[-1].append(p)

        def _curveToOne(self, p1, p2, p3):
            p0 = self.polys[-1][-1]
            for k in range(1, self.steps + 1):
                t = k / self.steps
                u = 1 - t
                self.polys[-1].append(
                    (
                        u**3 * p0[0]
                        + 3 * u * u * t * p1[0]
                        + 3 * u * t * t * p2[0]
                        + t**3 * p3[0],
                        u**3 * p0[1]
                        + 3 * u * u * t * p1[1]
                        + 3 * u * t * t * p2[1]
                        + t**3 * p3[1],
                    )
                )

        def _qCurveToOne(self, p1, p2):
            p0 = self.polys[-1][-1]
            for k in range(1, self.steps + 1):
                t = k / self.steps
                u = 1 - t
                self.polys[-1].append(
                    (
                        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
                    )
                )

        def _closePath(self):
            pass

    return FlatPen(glyph_set)


def _outline(font, glyph: str, dx: float = 0.0) -> tuple[list, float]:
    """Polygons of *glyph* in em units, shifted by *dx*; and its advance (em)."""
    gs = font.getGlyphSet()
    upm = font["head"].unitsPerEm
    pen = _flat_pen(gs)
    gs[glyph].draw(pen)
    polys = [[(x / upm + dx, y / upm) for x, y in p] for p in pen.polys]
    return polys, font["hmtx"][glyph][0] / upm


def _raster(
    polys: list,
    step: float = 0.02,
    x0: float = -0.2,
    y0: float = -0.35,
    y1: float = 1.15,
) -> set:
    """Filled cells (even-odd) of the polygons on a grid of *step* em."""
    edges = []
    for p in polys:
        for i, a in enumerate(p):
            b = p[(i + 1) % len(p)]
            if a[1] != b[1]:
                edges.append((a, b))
    filled = set()
    for j in range(int((y1 - y0) / step)):
        y = y0 + (j + 0.5) * step
        xs = sorted(
            a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            for a, b in edges
            if (a[1] <= y) != (b[1] <= y)
        )
        for k in range(0, len(xs) - 1, 2):
            i0, i1 = int((xs[k] - x0) / step + 0.5), int((xs[k + 1] - x0) / step + 0.5)
            filled.update((i, j) for i in range(i0, i1))
    return filled


def _glyph_for_char(font, ch: str) -> str | None:
    """The glyph that draws *ch*: cmap (Unicode, then symbol / Mac tables), else a glyph named *ch*."""
    if "cmap" not in font:  # ligature-only subsets have none
        return ch if ch in font.getGlyphOrder() else None
    cmap = font.getBestCmap() or {}
    if ord(ch) in cmap:
        return cmap[ord(ch)]
    if "cmap" in font:
        for table in font["cmap"].tables:
            for code in (ord(ch), 0xF000 + ord(ch)):
                if code in table.cmap:
                    return table.cmap[code]
    return ch if ch in font.getGlyphOrder() else None


def identify(
    lig_font, glyph: str, letter_fonts: list
) -> tuple[str | None, list[tuple[float, str]]]:
    """Which letters *glyph* draws: (letters or None, [(score, candidate), …] best first)."""
    target = _raster(_outline(lig_font, glyph)[0])
    if not target:
        return None, []
    scores = []
    for cand in CANDIDATES:
        for font in letter_fonts:
            glyphs = [_glyph_for_char(font, c) for c in cand]
            if None in glyphs:
                continue
            polys, dx = [], 0.0
            for g in glyphs:
                p, adv = _outline(font, g, dx)
                polys += p
                dx += adv
            drawn = _raster(polys)
            scores.append((len(target & drawn) / max(1, len(target | drawn)), cand))
            break
    scores.sort(reverse=True)
    if (
        scores
        and scores[0][0] >= MIN_SCORE
        and (len(scores) == 1 or scores[0][0] - scores[1][0] >= MIN_MARGIN)
    ):
        return scores[0][1], scores
    return None, scores


# ── per document ─────────────────────────────────────────────────────────────


def _base(fontname: str) -> str:
    """'IHQKAT+OpenSans-Light' -> 'OpenSans-Light' (subset tag and -Identity-H dropped)."""
    name = fontname.split("+", 1)[-1]
    return name.removesuffix("-Identity-H")


@dataclass
class LigatureResolver:
    """Expands unmapped ligature glyphs of one open PDF; caches by (font xref, glyph id)."""

    pdf: Any
    cache: dict = field(default_factory=dict)
    unresolved: list = field(default_factory=list)  # (page, font, gid)
    _fonts: dict = field(default_factory=dict)
    _all_fonts: list | None = None

    def _font(self, xref: int):
        if xref not in self._fonts:
            try:
                from fontTools.ttLib import TTFont

                _name, _ext, _typ, buf = self.pdf.extract_font(xref)
                self._fonts[xref] = TTFont(io.BytesIO(buf)) if buf else None
            except Exception:
                logger.debug("Cannot read the embedded font %s", xref, exc_info=True)
                self._fonts[xref] = None
        return self._fonts[xref]

    def _doc_fonts(self) -> list:
        if self._all_fonts is None:
            seen = {}
            for pno in range(len(self.pdf)):
                for f in self.pdf.get_page_fonts(pno):
                    seen.setdefault(f[0], f)
            self._all_fonts = list(seen.values())
        return self._all_fonts

    def letters(
        self, page_no: int, page_fonts: list, span_font: str, gid: int
    ) -> str | None:
        """The letters glyph *gid* of the font *span_font* (as texttrace names it) draws."""
        # texttrace names the font without its subset tag and may cut it short
        cands = [
            f
            for f in page_fonts
            if _base(f[3]).startswith(span_font) or span_font.startswith(_base(f[3]))
        ]
        cands.sort(
            key=lambda f: f[2] != "Type0"
        )  # unmapped ligatures live in Type0 / Identity-H fonts
        for f in cands:
            key = (f[0], gid)
            if key not in self.cache:
                self.cache[key] = self._identify(f, gid)
            if self.cache[key]:
                return self.cache[key]
        self.unresolved.append((page_no, span_font, gid))
        logger.warning(
            "Unmapped glyph %s of font %s on page %d: cannot tell which letters it draws",
            gid,
            span_font,
            page_no,
        )
        return None

    def _identify(self, font_entry, gid: int) -> str | None:
        xref, fontname = font_entry[0], font_entry[3]
        font = self._font(xref)
        if font is None or ("glyf" not in font and "CFF " not in font):
            return None
        order = font.getGlyphOrder()
        if not 0 < gid < len(order):
            return None
        siblings = [font] + [
            self._font(f[0])
            for f in self._doc_fonts()
            if f[0] != xref and _base(f[3]) == _base(fontname)
        ]
        siblings = [s for s in siblings if s is not None]
        try:
            letters, scores = identify(font, order[gid], siblings)
        except Exception:
            logger.debug(
                "Outline comparison failed for %s gid %s", fontname, gid, exc_info=True
            )
            return None
        best = ", ".join(f"{c} {s:.2f}" for s, c in scores[:3])
        if letters:
            logger.info(
                "Ligature glyph %s of %s draws %r (%s)",
                gid,
                _base(fontname),
                letters,
                best,
            )
        else:
            logger.debug(
                "Glyph %s of %s matches no ligature clearly (%s)",
                gid,
                _base(fontname),
                best,
            )
        return letters


def page_text(
    page, resolver: LigatureResolver | None = None, flags: int | None = None
) -> str:
    """``page.get_text()`` with ligatures expanded (see the module docstring)."""
    import pymupdf

    flags = pymupdf.TEXTFLAGS_TEXT if flags is None else flags
    tp = page.get_textpage(flags=flags)
    text = tp.extractText()
    if not has_bad_chars(text):
        return expand_unicode_ligatures(text)

    # The plain text and the raw dict come from the same text page, in the same order:
    # the k-th bad character in the text is the k-th bad character in the dict.
    bad = []  # (span font, origin) in reading order
    for block in tp.extractRAWDICT().get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                bad.extend(
                    (span["font"], ch["origin"])
                    for ch in span["chars"]
                    if is_bad_char(ch["c"])
                )
    gids = {}  # rounded origin -> (font, gid), from the content stream
    for span in page.get_texttrace():
        for ucs, gid, origin, _bbox in span["chars"]:
            if ucs == 0xFFFD or ucs < 32:
                gids[(round(origin[0], 1), round(origin[1], 1))] = (span["font"], gid)

    resolver = resolver or LigatureResolver(page.parent)
    page_fonts = page.get_fonts()
    out, k = [], 0
    for c in text:
        if not is_bad_char(c):
            out.append(c)
            continue
        letters = None
        if k < len(bad):
            font, origin = bad[k]
            hit = gids.get((round(origin[0], 1), round(origin[1], 1)))
            if hit:
                letters = resolver.letters(page.number + 1, page_fonts, hit[0], hit[1])
            else:
                resolver.unresolved.append((page.number + 1, font, None))
                logger.warning(
                    "Unmapped character on page %d (font %s): no glyph found for it",
                    page.number + 1,
                    font,
                )
        k += 1
        out.append(letters or REPLACEMENT)
    if k != len(bad):
        logger.warning(
            "Page %d: %d unmapped characters in the text, %d in the layout",
            page.number + 1,
            k,
            len(bad),
        )
    return expand_unicode_ligatures("".join(out))
