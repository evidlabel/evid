"""DocIngester — sole deep PDF ingest path for an EvidenceSet.

Owns the full pipeline: source resolve (local path / URL) → content hash UUID →
copy as original.pdf → info.yml / evidmgr_meta.yml → label.typ → bibtex →
vector index. CLI and GUI adapters only load the set, call the ingester, and
handle optional UI (labeler, progress dialogs).
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

import arrow
import yaml

if TYPE_CHECKING:
    from evid.models import Document, EvidenceSet

logger = logging.getLogger(__name__)

# Progress callback: (step: int, total: int, message: str) -> None
ProgressCallback = Callable[[int, int, str], None]

_TOTAL_STEPS = 7


def _noop(step: int, total: int, msg: str) -> None:
    logger.debug("[%d/%d] %s", step, total, msg)


@dataclass
class ResolvedSource:
    """A local PDF ready for :meth:`DocIngester.ingest`, plus metadata hints.

    *temp_dir* (a ``tempfile.TemporaryDirectory``) must stay alive until the
    PDF has been copied into the set; :meth:`DocIngester.ingest` cleans it up
    when passed as *temp_dir*.
    """

    pdf_path: Path
    source_url: str = ""
    title: str = ""
    authors: str = ""
    dates: str = ""
    original_name: str = ""
    temp_dir: object | None = None  # tempfile.TemporaryDirectory | None


def resolve_source(source: str) -> ResolvedSource:
    """Resolve a local PDF path or HTTP(S) URL to a local PDF for ingest.

    For URLs: download a PDF response, or render an HTML page to PDF via Typst.
    Raises ``ValueError`` / ``FileNotFoundError`` / ``requests.RequestException``
    on failure (callers map these to UI / CLI exit codes).
    """
    is_url = source.startswith(("http://", "https://"))

    if not is_url:
        file_path = Path(source)
        if not file_path.exists():
            msg = f"File {file_path} does not exist."
            raise FileNotFoundError(msg)
        if file_path.suffix.lower() != ".pdf":
            msg = "File must be a PDF."
            raise ValueError(msg)
        return ResolvedSource(
            pdf_path=file_path,
            original_name=file_path.name,
        )

    import requests

    from evid.core.pdf_metadata import extract_html_date
    from evid.core.typst_generation import (
        _BROWSER_HEADERS,
        decoded_response_text,
        web_to_pdf,
    )

    response = requests.get(source, timeout=15, headers=_BROWSER_HEADERS)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    # Decode percent-encoding so non-ASCII filenames (e.g. Danish
    # "%C3%A5" → "å") become real characters in original_name / title hints.
    file_name = unquote(source.rsplit("/", maxsplit=1)[-1]) or "document"
    host = urlparse(source).netloc
    tmp = tempfile.TemporaryDirectory()

    # CDNs often serve PDFs as application/octet-stream (plus a
    # Content-Disposition filename). Trust the body magic, not only the type.
    if "application/pdf" in content_type.lower() or response.content.startswith(
        b"%PDF"
    ):
        file_name = Path(file_name).stem + ".pdf"
        pdf_path = Path(tmp.name) / file_name
        pdf_path.write_bytes(response.content)
        logger.debug("Downloaded PDF from URL: %s", file_name)
        return ResolvedSource(
            pdf_path=pdf_path,
            source_url=source,
            authors=host,
            original_name=file_name,
            temp_dir=tmp,
        )

    # HTML — render the page to a Typst-generated PDF.
    html_str = decoded_response_text(response)
    rendered_pdf, web_page_title = web_to_pdf(
        source,
        Path(tmp.name),
        html=html_str,
    )
    # Prefer the page's own publish date; the rendered PDF's creation date is
    # "now", which would otherwise become a wrong citation date.
    web_page_date = extract_html_date(html_str)
    logger.debug(
        "Rendered HTML→PDF: %s (title=%r date=%r)",
        rendered_pdf.name,
        web_page_title,
        web_page_date,
    )
    return ResolvedSource(
        pdf_path=rendered_pdf,
        source_url=source,
        title=web_page_title,
        authors=host,
        dates=web_page_date,
        original_name=rendered_pdf.name,
        temp_dir=tmp,
    )


class DocIngester:
    """Ingest a PDF into an EvidenceSet, running the full evid pipeline."""

    def __init__(
        self,
        vec_service: object | None = None,  # VecService | None
        progress: ProgressCallback = _noop,
    ) -> None:
        self.vec_service = vec_service
        self.progress = progress
        self._errors: list[tuple[int, str, str]] = []  # (step, label, error)
        self._last_was_existing: bool = False

    @property
    def errors(self) -> list[tuple[int, str, str]]:
        """Step-level errors accumulated during the last ingest call."""
        return list(self._errors)

    @property
    def last_was_existing(self) -> bool:
        """True if the last :meth:`ingest` returned an already-present document."""
        return self._last_was_existing

    def ingest_source(
        self,
        source: str,
        evidence_set: EvidenceSet,
        label: str = "",
        title: str = "",
        authors: str = "",
        dates: str = "",
        tags: list[str] | None = None,
        do_index: bool = True,
        pool: object | None = None,
    ) -> Document:
        """Resolve *source* (path or URL) and run the full ingest pipeline.

        Caller-supplied *title* / *authors* / *dates* / *label* override both
        URL-derived hints and PDF-extracted metadata. *pool* is an optional
        long-lived ``IndexWorkerPool`` reused across a batch.
        """
        resolved = resolve_source(source)
        return self.ingest(
            pdf_path=resolved.pdf_path,
            evidence_set=evidence_set,
            label=label,
            title=title or resolved.title,
            authors=authors or resolved.authors,
            dates=dates or resolved.dates,
            tags=tags,
            source_url=resolved.source_url,
            temp_dir=resolved.temp_dir,
            do_index=do_index,
            pool=pool,
        )

    def ingest(
        self,
        pdf_path: Path,
        evidence_set: EvidenceSet,
        label: str = "",
        title: str = "",
        authors: str = "",
        dates: str = "",
        tags: list[str] | None = None,
        source_url: str = "",
        temp_dir: object = None,
        do_index: bool = True,
        pool: object | None = None,
    ) -> Document:
        """Ingest a single PDF into *evidence_set*. Returns the new Document.

        User-supplied *title*, *authors*, *dates* win over values auto-extracted
        from PDF metadata.  *temp_dir* (a ``tempfile.TemporaryDirectory``) is
        cleaned up after the file is copied, if provided.

        When *do_index* is False the slow step-6 vector index is skipped; the doc
        is added but left ``indexed=False`` so it can be indexed later (e.g. via a
        background queue or ``index_existing``).

        The PDF is always stored as ``original.pdf``.
        """
        tags = tags or []
        p = self.progress
        n = _TOTAL_STEPS
        self._errors = []  # reset per-call so previous failures don't persist
        self._last_was_existing = False

        # ── 1. Content hash → UUID ────────────────────────────────────────────
        p(1, n, f"Computing UUID for {pdf_path.name}")
        logger.debug("Ingesting '%s' into set '%s'", pdf_path.name, evidence_set.slug)
        with pdf_path.open("rb") as f:
            content_bytes = f.read()
        digest = hashlib.sha256(content_bytes).digest()[:16]
        doc_uuid = uuid.UUID(bytes=digest).hex
        logger.debug("SHA-256 UUID: %s", doc_uuid)

        doc_dir = evidence_set.path / "docs" / doc_uuid
        if doc_dir.exists():
            logger.debug(
                "Already ingested: %s in '%s' — skipping", doc_uuid, evidence_set.slug
            )
            self._last_was_existing = True
            from evid.core.doc_loader import load_document

            return load_document(doc_dir, doc_uuid)

        # ── 2. Copy PDF ───────────────────────────────────────────────────────
        p(2, n, "Copying PDF")
        doc_dir.mkdir(parents=True)
        original_pdf = doc_dir / "original.pdf"
        shutil.copy2(pdf_path, original_pdf)
        logger.debug("Copied PDF to %s", original_pdf)

        # Clean up temp download dir now that the file is safely copied
        if temp_dir is not None:
            try:
                temp_dir.cleanup()
                logger.debug("Cleaned up temp download dir")
            except Exception:
                pass

        # ── 3. Extract metadata + create info.yml / evidmgr_meta.yml ──────────
        p(3, n, "Extracting PDF metadata")
        from evid.core.pdf_metadata import extract_pdf_metadata
        from evid.models import InfoModel

        auto_title, auto_authors, auto_date = extract_pdf_metadata(
            original_pdf, pdf_path.name
        )
        logger.debug(
            "Auto-extracted: title=%r authors=%r date=%r",
            auto_title,
            auto_authors,
            auto_date,
        )

        # User-supplied values win over auto-extracted
        doc_title = title or auto_title or pdf_path.stem
        doc_authors = authors or auto_authors
        doc_dates = dates or auto_date
        doc_label = label or doc_title
        logger.debug(
            "Metadata: label=%r title=%r authors=%r", doc_label, doc_title, doc_authors
        )

        info = {
            "original_name": "original.pdf",
            "uuid": doc_uuid,
            "time_added": arrow.now().format("YYYY-MM-DD"),
            "dates": doc_dates,
            "title": doc_title,
            "authors": doc_authors,
            "tags": ",".join(tags),
            "label": doc_label,
            "url": source_url,
        }
        try:
            info = InfoModel(**info).model_dump()
        except Exception:
            logger.exception("InfoModel validation failed for %s", doc_uuid)

        with (doc_dir / "info.yml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(info, f, allow_unicode=True)
        logger.debug("Wrote info.yml")

        meta = {
            "notes": "",
            "indexed": False,
        }
        from evid.core.evid_meta import write_meta

        write_meta(doc_dir, meta)

        # ── 4. Generate .typ file ─────────────────────────────────────────────
        p(4, n, "Extracting text to Typst")
        typ_path = doc_dir / "label.typ"
        try:
            from evid.core.typst_generation import textpdf_to_typst

            textpdf_to_typst(original_pdf, typ_path)
            logger.debug(
                "Generated label.typ (%d bytes)",
                typ_path.stat().st_size if typ_path.exists() else 0,
            )
        except Exception as exc:
            logger.exception("textpdf_to_typst failed for %s", doc_uuid)
            self._errors.append((4, "extract typst text", str(exc)))

        # ── 5. typst query → label.json + label.bib ───────────────────────────
        p(5, n, "Running typst query → label.json / label.bib")
        try:
            from evid.core.bibtex import generate_bib_from_typ

            ok, msg = generate_bib_from_typ(typ_path)
            if ok:
                logger.debug("BibTeX generation succeeded for %s", doc_uuid)
            else:
                logger.warning("BibTeX generation issue for %s: %s", doc_uuid, msg)
        except Exception as exc:
            logger.exception("generate_bib_from_typ failed for %s", doc_uuid)
            self._errors.append((5, "generate bib from typ", str(exc)))

        # ── 6. Vector index ───────────────────────────────────────────────────
        doc = self._make_document(doc_dir, doc_uuid, doc_label, tags, source_url)
        if not do_index:
            logger.debug("Skipping vector index for %s (do_index=False)", doc_uuid)
        elif self.vec_service is not None:
            p(6, n, "Indexing into vector store")
            try:
                typ_text = (
                    typ_path.read_text(encoding="utf-8") if typ_path.exists() else ""
                )
                logger.debug("Embedding %d chars for %s", len(typ_text), doc_uuid)
                ok, msg = self.vec_service.index_document_isolated(  # type: ignore[attr-defined]
                    doc, typ_text, evidence_set, pool=pool
                )
                if ok:
                    meta["indexed"] = True
                    logger.debug("Vector index updated for %s", doc_uuid)
                else:
                    logger.warning("Vector index skipped for %s: %s", doc_uuid, msg)
                    # Close the ChromaDB client on failure to free the file lock.
                    close_vec_service(self.vec_service, evidence_set.slug)
            except Exception as exc:
                logger.exception("VecService.index_document failed for %s", doc_uuid)
                self._errors.append((6, "vector index", str(exc)))
                # Close the ChromaDB client on unexpected errors too.
                close_vec_service(self.vec_service, evidence_set.slug)
        else:
            logger.debug("No VecService configured — skipping vector index")

        if self._errors:
            logger.warning(
                "Document ingested with %d step failure(s) for %s: %s",
                len(self._errors),
                doc_uuid,
                "; ".join(f"[{step}] {label}" for step, label, _ in self._errors),
            )

        # ── 7. Update evidmgr_meta.yml ────────────────────────────────────────
        p(7, n, "Finalising metadata")
        from evid.core.evid_meta import write_meta

        write_meta(doc_dir, meta)

        logger.debug("Ingested %s into set '%s'", doc_uuid, evidence_set.slug)
        return doc

    def index_existing(
        self,
        doc_dir: Path,
        evidence_set: EvidenceSet,
        pool: object | None = None,
    ) -> bool:
        """Index an already-imported document that has a .typ file but no vecdb entry.

        *pool* is an optional long-lived ``IndexWorkerPool`` reused across a
        batch so the embedding model loads once. Returns True if indexing
        succeeded.
        """
        if self.vec_service is None:
            logger.warning("No VecService configured; cannot index %s", doc_dir.name)
            return False

        from evid.core.doc_loader import load_document

        # Load the document
        doc = load_document(doc_dir, doc_dir.name)

        # Find the typ file (evid uses label.typ; fallback to any *.typ)
        typ_path = doc_dir / "label.typ"
        if not typ_path.exists():
            candidates = list(doc_dir.glob("*.typ"))
            typ_path = candidates[0] if candidates else None

        typ_text = typ_path.read_text(encoding="utf-8") if typ_path else ""
        if not typ_text:
            logger.warning(
                "No .typ text for %s; indexing with empty content", doc_dir.name
            )
        else:
            logger.debug(
                "Embedding %d chars for existing doc %s", len(typ_text), doc_dir.name
            )

        logger.debug(
            "Indexing existing doc %s into '%s'", doc_dir.name, evidence_set.slug
        )
        try:
            ok, msg = self.vec_service.index_document_isolated(
                doc, typ_text, evidence_set, pool=pool
            )
            if not ok:
                logger.warning("Isolated index failed for %s: %s", doc_dir.name, msg)
                return False
        except Exception:
            logger.exception("VecService.index_document failed for %s", doc_dir.name)
            return False

        from evid.core.evid_meta import read_meta, write_meta

        meta = read_meta(doc_dir)
        meta["indexed"] = True
        write_meta(doc_dir, meta)

        logger.debug(
            "Indexed existing doc %s into set '%s'", doc_dir.name, evidence_set.slug
        )
        return True

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_document(
        self,
        doc_dir: Path,
        doc_uuid: str,
        label: str,
        tags: list[str],
        source_url: str,
    ) -> Document:
        from evid.models import Document

        return Document(
            uuid=doc_uuid,
            path=doc_dir,
            label=label,
            tags=tags,
            added=datetime.now(tz=UTC),
            source_url=source_url,
        )


def close_vec_service(vec_service: object | None, slug: str) -> None:
    """Call VecService.close(slug) if *vec_service* supports it.

    This is a runtime duck-typed helper because VecService is only
    imported inside TYPE_CHECKING blocks.
    """
    if vec_service is not None and hasattr(vec_service, "close"):
        try:
            vec_service.close(slug)  # type: ignore[union-attr]
        except Exception:
            logger.debug(
                "Failed to close VecService client for %s", slug, exc_info=True
            )
