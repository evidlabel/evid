"""Screenshots as one document.

Issuu-style viewers show the pages and do not hand over the PDF. Each image
is one page. Tesseract (through PyMuPDF) writes a hidden text layer, and the
resulting PDF goes through :class:`evid.services.doc_ingester.DocIngester`
like any other file. The text layer is what later extraction reads, so a
refresh does not wipe the words. A multi-column page is rewritten so the
text reads down each column; a single column is left as Tesseract wrote it.

:func:`ocr_pixmap` is the Tesseract call. Tests replace it; CI has no
Tesseract.
"""

from __future__ import annotations

import itertools
import logging
import re
import statistics
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".tif",
    ".tiff",
    ".bmp",
}
DEFAULT_LANG = "dan+eng"
# Whole-document annotation written once, when the document is new.
SCREENSHOT_NOTE = "Text is OCR of screenshots. This is not the publisher PDF."
TESSERACT_HINT = (
    "Screenshot text needs Tesseract. "
    "Install tesseract-ocr and the language data (tesseract-ocr-dan)."
)
# Long edge of a stored page, in PDF points. Pixels are not resampled:
# the pixmap dpi is raised so a screen capture is not a 26-inch page.
_LONG_PT = 1000

# (step, total, filename) — step is 1-based.
Progress = Callable[[int, int, str], None]

_NUM = re.compile(r"(\d+)")
_LANG = re.compile(r"[A-Za-z0-9_-]+")
_tessdata: str | None = None
_langs_ok: set[str] = set()


def natural_name(name: str) -> tuple:
    """Sort key: ``page2`` before ``page10``, case-insensitive."""
    parts = _NUM.split(name.casefold())
    key: list[tuple] = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


@dataclass(frozen=True)
class ShotSet:
    """Pages in ingest order, plus the title and PDF name they imply."""

    images: list[Path]
    title: str
    source_name: str


def collect_images(sources: list[str]) -> ShotSet:
    """Images from files and directories, in argument order.

    A directory contributes its images in :func:`natural_name` order and
    skips other files with a warning. A file that is not an image is an
    error. One directory becomes ``<name>.pdf``; several paths become
    ``screenshots.pdf``.
    """
    if not sources:
        raise ValueError("No screenshots to add.")
    images: list[Path] = []
    dirs = 0
    files = 0
    only_dir: Path | None = None
    for source in sources:
        path = Path(source).expanduser()
        if path.is_dir():
            dirs += 1
            only_dir = path
            found, others = _dir_images(path)
            if not found:
                logger.warning("No screenshots found in directory %s", path)
            elif others:
                logger.warning(
                    "Skipping %d file(s) in %s that are not images",
                    len(others),
                    path,
                )
            images.extend(found)
            continue
        if not path.is_file():
            raise FileNotFoundError(f"File {path} does not exist.")
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f"File must be an image: {path.name}")
        files += 1
        images.append(path)
    if not images:
        raise ValueError("No screenshots to add.")
    if dirs == 1 and files == 0 and only_dir is not None:
        return ShotSet(images, only_dir.name, f"{only_dir.name}.pdf")
    stem = images[0].stem
    source_name = "screenshots.pdf" if len(images) > 1 else f"{stem}.pdf"
    return ShotSet(images, stem, source_name)


def _dir_images(path: Path) -> tuple[list[Path], list[Path]]:
    found: list[Path] = []
    others: list[Path] = []
    for child in path.iterdir():
        if child.name.startswith(".") or not child.is_file():
            continue
        if child.suffix.lower() in IMAGE_SUFFIXES:
            found.append(child)
        else:
            others.append(child)
    found.sort(key=lambda p: natural_name(p.name))
    return found, others


def require_ocr(lang: str) -> str:
    """Tessdata directory, or ``ValueError`` with the install hint.

    The lookup is remembered. A missing language pack names the package
    (``tesseract-ocr-dan``).
    """
    global _tessdata
    if _tessdata is None:
        try:
            import pymupdf

            _tessdata = pymupdf.get_tessdata(None)
        except Exception as exc:
            raise ValueError(TESSERACT_HINT) from exc
    for code in _lang_codes(lang):
        if code in _langs_ok:
            continue
        if not (Path(_tessdata) / f"{code}.traineddata").is_file():
            raise ValueError(
                f"Tesseract has no language data for {code!r}. "
                f"Install tesseract-ocr-{code}. ({TESSERACT_HINT})"
            )
        _langs_ok.add(code)
    return _tessdata


def _lang_codes(lang: str) -> list[str]:
    codes = [c.strip() for c in (lang or DEFAULT_LANG).split("+") if c.strip()]
    if not codes:
        raise ValueError("Give a Tesseract language, for example dan+eng.")
    for code in codes:
        if not _LANG.fullmatch(code):
            raise ValueError(f"Bad Tesseract language {code!r}.")
    return codes


def ocr_pixmap(pix, lang: str) -> bytes:
    """One searchable PDF page of *pix*. Tests replace this.

    The page reads down the left column, then the next. A single column
    stays the Tesseract bytes, so its content hash does not move.
    """
    require_ocr(lang)
    try:
        raw = pix.pdfocr_tobytes(compress=True, language=lang or DEFAULT_LANG)
    except Exception as exc:
        raise ValueError(f"OCR failed ({lang}). {TESSERACT_HINT}") from exc
    return _reading_order(raw)


def screenshots_to_pdf(
    images: list[Path],
    dest: Path,
    lang: str = DEFAULT_LANG,
    progress: Progress | None = None,
) -> Path:
    """Write *images* as one PDF. One bad page fails the whole build."""
    import pymupdf

    if not images:
        raise ValueError("No screenshots to add.")
    dest = Path(dest)
    out = pymupdf.open()
    try:
        total = len(images)
        for i, image in enumerate(images, start=1):
            if progress is not None:
                progress(i, total, image.name)
            try:
                pix = _load_pixmap(image)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"Cannot read {image.name}.") from exc
            _fit_page(pix)
            try:
                raw = ocr_pixmap(pix, lang)
            except ValueError as exc:
                raise ValueError(f"{image.name}: {exc}") from exc
            page_pdf = pymupdf.open(stream=raw, filetype="pdf")
            try:
                if page_pdf.page_count < 1:
                    raise ValueError(f"{image.name}: OCR did not return a page.")
                out.insert_pdf(page_pdf)
            finally:
                page_pdf.close()
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.set_metadata({})
        out.save(
            str(dest),
            garbage=4,
            deflate=True,
            no_new_id=True,
            reproducible=True,
        )
    finally:
        out.close()
    return dest


def resolve_screenshots(
    sources: list[str],
    lang: str = DEFAULT_LANG,
    progress: Progress | None = None,
):
    """A :class:`~evid.services.doc_ingester.ResolvedSource` for these pages.

    *temp_dir* stays alive until ingest copies the PDF.
    """
    from evid.services.doc_ingester import ResolvedSource

    shot = collect_images(list(sources))
    tmp = tempfile.TemporaryDirectory()
    try:
        pdf_path = Path(tmp.name) / shot.source_name
        screenshots_to_pdf(shot.images, pdf_path, lang=lang, progress=progress)
    except Exception:
        tmp.cleanup()
        raise
    return ResolvedSource(
        pdf_path=pdf_path,
        title=shot.title,
        original_name=shot.source_name,
        temp_dir=tmp,
    )


def annotate_screenshot(doc_dir: Path) -> None:
    """Note that the text is OCR of screenshots, not the publisher PDF."""
    from evid.core.labels import add_document_annotation

    add_document_annotation(doc_dir, SCREENSHOT_NOTE, by="evid")


def _load_pixmap(path: Path):
    """The image's own pixels, as grey or RGB (what pdfocr accepts)."""
    import pymupdf

    pix = None
    try:
        pix = pymupdf.Pixmap(str(path))
    except Exception:
        pix = None
    if pix is None or pix.width <= 0 or pix.height <= 0:
        try:
            doc = pymupdf.open(path)
        except Exception as exc:
            raise ValueError(f"Cannot read {path.name}.") from exc
        try:
            if doc.page_count < 1:
                raise ValueError(f"Cannot read {path.name}.")
            page = doc[0]
            info = page.get_image_info() or []
            zoom = info[0]["width"] / page.rect.width if info and page.rect.width else 1
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        finally:
            doc.close()
    return _rgb_or_gray(pix)


def _rgb_or_gray(pix):
    import pymupdf

    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    n = pix.colorspace.n if pix.colorspace is not None else pix.n
    if n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return pix


def _fit_page(pix) -> None:
    """Raise dpi so the long edge is at most ``_LONG_PT``, without resampling."""
    long_px = max(pix.width, pix.height)
    if long_px <= 0:
        return
    dpi = pix.xres or 96
    if long_px * 72 / dpi <= _LONG_PT:
        return
    need = max(1, round(long_px * 72 / _LONG_PT))
    pix.set_dpi(int(need), int(need))


def _reading_order(raw: bytes) -> bytes:
    """Column order for a Tesseract page, or *raw* when there is nothing to do.

    Words that share a baseline are one text line, so two columns come out
    left, right, left, right. Lines are grouped by that baseline, a gap that
    repeats down the page is a gutter, and the hidden text is written again
    one visual line at a time: the whole left column, then the next. The
    screenshot image stays. A single column, a table of short cells, and
    text that is already in this order keep *raw* so the content hash stays.
    """
    import pymupdf

    try:
        doc = pymupdf.open(stream=raw, filetype="pdf")
    except Exception:
        logger.debug("Column order left the OCR bytes unchanged", exc_info=True)
        return raw
    try:
        changed = False
        for page in doc:
            pieces = _column_pieces(page)
            if not pieces:
                continue
            if not _write_column_pieces(page, pieces):
                logger.debug("Column order rewrite did not stick; keeping OCR text")
                return raw
            changed = True
        if not changed:
            return raw
        logger.debug("OCR text rewritten into column order")
        return doc.tobytes(garbage=4, deflate=True, no_new_id=True, reproducible=True)
    except Exception:
        logger.debug("Column order left the OCR bytes unchanged", exc_info=True)
        return raw
    finally:
        doc.close()


def _column_pieces(page) -> list[tuple] | None:
    """Visual lines in column order, or ``None`` when the page should stay."""
    words = _page_words(page)
    if len(words) < 4:
        return None
    width = float(page.rect.width)
    if width <= 0:
        return None
    lines = _line_groups(words)
    gutters, threshold = _column_gutters(lines, width)
    if not gutters:
        return None
    prepared = [_split_at_gutters(line, gutters, threshold) for line in lines]
    counts = [
        len(part)
        for parts in prepared
        for part in parts
        if not _crosses_gutter(part, gutters)
    ]
    # A table of one-word cells has no small gaps inside a cell, so it never
    # reaches here. Two-word cells can. Real columns are phrases.
    if not counts or statistics.median(counts) < 2:
        return None
    ordered = _order_pieces(lines, prepared, gutters)
    plain = _plain_lines(page)
    if _tokens(text for *_, text in ordered) == _tokens(plain):
        return None
    return ordered


def _write_column_pieces(page, pieces: list[tuple]) -> bool:
    """Replace the text layer. The image and line art stay. Invisible text."""
    import pymupdf

    page.add_redact_annot(page.rect)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
    )
    for x0, _y0, _x1, y1, text in pieces:
        height = max(y1 - _y0, 1)
        page.insert_text(
            (x0, y1),
            text,
            fontsize=height * 0.75,
            fontname="helv",
            render_mode=3,
        )
    return _plain_lines(page) == [text for *_, text in pieces]


def _plain_lines(page) -> list[str]:
    return [line.strip() for line in page.get_text().splitlines() if line.strip()]


def _tokens(lines) -> list[str]:
    return [word for line in lines for word in line.split()]


def _page_words(page) -> list[tuple]:
    words = []
    for word in page.get_text("words"):
        text = str(word[4]).strip()
        if not text:
            continue
        x0, y0, x1, y1 = (
            float(word[0]),
            float(word[1]),
            float(word[2]),
            float(word[3]),
        )
        if x1 > x0 and y1 > y0:
            words.append((x0, y0, x1, y1, text))
    return words


def _line_groups(words: list[tuple]) -> list[list[tuple]]:
    """Words on one baseline, top to bottom. Each line is left to right."""
    height = statistics.median(word[3] - word[1] for word in words)
    tolerance = max(height * 0.45, 1.5)
    words = sorted(words, key=lambda word: (word[1], word[0]))
    lines: list[list[tuple]] = []
    for word in words:
        if not lines or word[1] - lines[-1][0][1] > tolerance:
            lines.append([word])
        else:
            lines[-1].append(word)
    for line in lines:
        line.sort(key=lambda word: word[0])
    return lines


def _column_gutters(
    lines: list[list[tuple]], width: float
) -> tuple[list[float], float]:
    """X positions of gaps that repeat down the page, and the gap size that counts."""
    gaps = [
        right[0] - left[2]
        for line in lines
        for left, right in itertools.pairwise(line)
        if right[0] > left[2]
    ]
    if not gaps:
        return [], 0
    threshold = max(3 * statistics.median(gaps), 0.04 * width, 12)
    slack = max(18.0, 0.04 * width)
    big: list[tuple[float, int]] = []
    for index, line in enumerate(lines):
        for left, right in itertools.pairwise(line):
            if right[0] - left[2] > threshold:
                big.append(((left[2] + right[0]) / 2, index))
    clusters: list[list[tuple[float, int]]] = []
    for mid, index in sorted(big):
        placed = False
        for cluster in clusters:
            center = statistics.median(item[0] for item in cluster)
            if abs(mid - center) <= slack:
                cluster.append((mid, index))
                placed = True
                break
        if not placed:
            clusters.append([(mid, index)])
    # One wide space is a sentence, not a column. The gutter has to show
    # up on several lines.
    need = max(2, round(0.3 * len(lines)))
    gutters = [
        statistics.median(item[0] for item in cluster)
        for cluster in clusters
        if len({item[1] for item in cluster}) >= need
    ]
    return sorted(gutters), threshold


def _split_at_gutters(line: list[tuple], gutters: list[float], threshold: float):
    pieces = [[line[0]]]
    for left, right in itertools.pairwise(line):
        gap = right[0] - left[2]
        crosses = gap > threshold and any(
            left[2] - 1 <= gutter <= right[0] + 1 for gutter in gutters
        )
        if crosses:
            pieces.append([right])
        else:
            pieces[-1].append(right)
    return pieces


def _crosses_gutter(words: list[tuple], gutters: list[float]) -> bool:
    x0 = min(word[0] for word in words)
    x1 = max(word[2] for word in words)
    return any(x0 + 1 < gutter < x1 - 1 for gutter in gutters)


def _column_index(words: list[tuple], gutters: list[float]) -> int:
    x0 = min(word[0] for word in words)
    x1 = max(word[2] for word in words)
    center = (x0 + x1) / 2
    return sum(center > gutter for gutter in gutters)


def _piece_box(words: list[tuple]) -> tuple:
    return (
        min(word[0] for word in words),
        min(word[1] for word in words),
        max(word[2] for word in words),
        max(word[3] for word in words),
        " ".join(word[4] for word in words),
    )


def _order_pieces(lines, prepared, gutters: list[float]) -> list[tuple]:
    """Title and footer stay put. Column lines flush left to right."""
    tops = [line[0][1] for line in lines]
    steps = [b - a for a, b in itertools.pairwise(tops) if b > a]
    leading = statistics.median(steps) if steps else 14
    detach = max(2.2 * leading, leading + 8)
    buckets: list[list[tuple]] = [[] for _ in gutters]
    buckets.append([])
    ordered: list[tuple] = []

    def flush() -> None:
        for bucket in buckets:
            ordered.extend(bucket)
            bucket.clear()

    previous = None
    for line, parts in zip(lines, prepared, strict=True):
        top = line[0][1]
        gap = 0 if previous is None else top - previous
        previous = top
        spans = [part for part in parts if _crosses_gutter(part, gutters)]
        columns = [part for part in parts if not _crosses_gutter(part, gutters)]
        # A line that crosses the gutter with no column gap is a title or a
        # footer. A line well below the columns, and only in one of them, is
        # a footer too. The tail of a longer column is not: its gap is one
        # line, so it stays in that column.
        detached = gap > detach and any(buckets) and len(parts) == 1
        if (spans and not columns) or detached:
            flush()
            ordered.append(_piece_box(line))
            continue
        for part in columns:
            buckets[_column_index(part, gutters)].append(_piece_box(part))
        if spans:
            flush()
            ordered.extend(_piece_box(part) for part in spans)
    flush()
    return ordered
