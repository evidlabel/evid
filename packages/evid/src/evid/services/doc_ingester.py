"""DocIngester — full PDF ingest pipeline for an EvidenceSet."""

from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import arrow
import yaml

if TYPE_CHECKING:
    from evid.models import Document, EvidenceSet

logger = logging.getLogger(__name__)

# Progress callback: (step: int, total: int, message: str) -> None
ProgressCallback = Callable[[int, int, str], None]

_TOTAL_STEPS = 7


def _noop(step: int, total: int, msg: str) -> None:
    logger.info("[%d/%d] %s", step, total, msg)


class DocIngester:
    """Ingest a PDF into an EvidenceSet, running the full evid pipeline."""

    def __init__(
        self,
        vec_service: object | None = None,  # VecService | None
        progress: ProgressCallback = _noop,
    ) -> None:
        self.vec_service = vec_service
        self.progress = progress

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
    ) -> Document:
        """Ingest a single PDF into *evidence_set*. Returns the new Document.

        User-supplied *title*, *authors*, *dates* win over values auto-extracted
        from PDF metadata.  *temp_dir* (a ``tempfile.TemporaryDirectory``) is
        cleaned up after the file is copied, if provided.

        When *do_index* is False the slow step-6 vector index is skipped; the doc
        is added but left ``indexed=False`` so it can be indexed later (e.g. via a
        background queue or ``index_existing``).
        """
        tags = tags or []
        p = self.progress
        n = _TOTAL_STEPS

        # ── 1. Content hash → UUID ────────────────────────────────────────────
        p(1, n, f"Computing UUID for {pdf_path.name}")
        logger.info("Ingesting '%s' into set '%s'", pdf_path.name, evidence_set.slug)
        with pdf_path.open("rb") as f:
            content_bytes = f.read()
        digest = hashlib.sha256(content_bytes).digest()[:16]
        doc_uuid = uuid.UUID(bytes=digest).hex
        logger.debug("SHA-256 UUID: %s", doc_uuid)

        doc_dir = evidence_set.path / "docs" / doc_uuid
        if doc_dir.exists():
            logger.info(
                "Already ingested: %s in '%s' — skipping", doc_uuid, evidence_set.slug
            )
            return self._load_existing(doc_dir, doc_uuid)

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

        # ── 3. Extract metadata + write info.yml / evidmgr_meta.yml ──────────
        p(3, n, "Extracting PDF metadata")
        from evid.core.models import InfoModel
        from evid.core.pdf_metadata import extract_pdf_metadata

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
        logger.info(
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
        except Exception:
            logger.exception("textpdf_to_typst failed for %s", doc_uuid)

        # ── 5. typst query → label.json + label.bib ───────────────────────────
        p(5, n, "Running typst query → label.json / label.bib")
        try:
            from evid.core.bibtex import generate_bib_from_typ

            ok, msg = generate_bib_from_typ(typ_path)
            if ok:
                logger.debug("BibTeX generation succeeded for %s", doc_uuid)
            else:
                logger.warning("BibTeX generation issue for %s: %s", doc_uuid, msg)
        except Exception:
            logger.exception("generate_bib_from_typ failed for %s", doc_uuid)

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
                # Run in a subprocess: a native crash in chromadb /
                # sentence-transformers must not take down the host app.
                ok, msg = self.vec_service.index_document_isolated(
                    doc, typ_text, evidence_set
                )
                if ok:
                    meta["indexed"] = True
                    logger.info("Vector index updated for %s", doc_uuid)
                else:
                    logger.warning("Vector index skipped for %s: %s", doc_uuid, msg)
            except Exception:
                logger.exception("VecService.index_document failed for %s", doc_uuid)
        else:
            logger.debug("No VecService configured — skipping vector index")

        # ── 7. Update evidmgr_meta.yml ────────────────────────────────────────
        p(7, n, "Finalising metadata")
        from evid.core.evid_meta import write_meta

        write_meta(doc_dir, meta)

        logger.info("Ingested %s into set '%s'", doc_uuid, evidence_set.slug)
        return doc

    def index_existing(
        self,
        doc_dir: Path,
        evidence_set: EvidenceSet,
    ) -> bool:
        """Index an already-imported document that has a .typ file but no vecdb entry.

        Returns True if indexing succeeded.
        """
        if self.vec_service is None:
            logger.warning("No VecService configured; cannot index %s", doc_dir.name)
            return False

        # Load the document
        doc = self._load_existing(doc_dir, doc_dir.name)

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

        logger.info(
            "Indexing existing doc %s into '%s'", doc_dir.name, evidence_set.slug
        )
        try:
            ok, msg = self.vec_service.index_document_isolated(
                doc, typ_text, evidence_set
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

        logger.info(
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

    def _load_existing(self, doc_dir: Path, doc_uuid: str) -> Document:
        """Load a Document that was already ingested."""
        from evid.models import Document

        info_path = doc_dir / "info.yml"
        from evid.core.evid_meta import read_meta

        with info_path.open("r", encoding="utf-8") as f:
            info = yaml.safe_load(f) or {}
        meta = read_meta(doc_dir)

        tags_raw = info.get("tags", "")
        if isinstance(tags_raw, list):
            tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        else:
            tags = (
                [t.strip() for t in str(tags_raw).split(",") if t.strip()]
                if tags_raw
                else []
            )

        return Document(
            uuid=doc_uuid,
            path=doc_dir,
            label=info.get("label", ""),
            tags=tags,
            added=datetime.now(tz=UTC),
            indexed=meta.get("indexed", False),
            notes=meta.get("notes", ""),
            source_url=info.get("url", ""),
        )
