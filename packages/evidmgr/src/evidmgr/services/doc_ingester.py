"""DocIngester — full PDF ingest pipeline for an EvidenceSet."""

from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import arrow
import yaml

if TYPE_CHECKING:
    from evidmgr.models import Document, EvidenceSet

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
        evidence_set: "EvidenceSet",
        label: str = "",
        tags: list[str] | None = None,
        source_type: str = "other",
        source_url: str = "",
    ) -> "Document":
        """Ingest a single PDF into *evidence_set*. Returns the new Document."""
        from evidmgr.models import Document, SourceType

        tags = tags or []
        p = self.progress
        n = _TOTAL_STEPS

        # ── 1. Content hash → UUID ────────────────────────────────────────────
        p(1, n, f"Computing UUID for {pdf_path.name}")
        with pdf_path.open("rb") as f:
            content_bytes = f.read()
        digest = hashlib.sha256(content_bytes).digest()[:16]
        doc_uuid = uuid.UUID(bytes=digest).hex

        doc_dir = evidence_set.path / "docs" / doc_uuid
        if doc_dir.exists():
            logger.info("Document %s already ingested into %s", doc_uuid, evidence_set.slug)
            return self._load_existing(doc_dir, doc_uuid)

        # ── 2. Copy PDF ───────────────────────────────────────────────────────
        p(2, n, "Copying PDF")
        doc_dir.mkdir(parents=True)
        original_pdf = doc_dir / "original.pdf"
        shutil.copy2(pdf_path, original_pdf)

        # ── 3. Extract metadata + write info.yml / evidmgr_meta.yml ──────────
        p(3, n, "Extracting PDF metadata")
        from evid.core.pdf_metadata import extract_pdf_metadata
        from evid.core.models import InfoModel

        title, authors, date = extract_pdf_metadata(original_pdf, pdf_path.name)
        doc_label = label or title or pdf_path.stem

        info = {
            "original_name": "original.pdf",
            "uuid": doc_uuid,
            "time_added": arrow.now().format("YYYY-MM-DD"),
            "dates": date,
            "title": title,
            "authors": authors,
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

        meta = {
            "source_type": source_type,
            "notes": "",
            "indexed": False,
            "anon_pending": False,
        }
        with (doc_dir / "evidmgr_meta.yml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True)

        # ── 4. Generate .typ file ─────────────────────────────────────────────
        p(4, n, "Extracting text to Typst")
        typ_path = doc_dir / f"{doc_uuid}.typ"
        try:
            from evid.core.typst_generation import textpdf_to_typst
            textpdf_to_typst(str(original_pdf), str(typ_path))
        except Exception:
            logger.exception("textpdf_to_typst failed for %s", doc_uuid)

        # ── 5. typst query → label.json + label.bib ───────────────────────────
        p(5, n, "Generating label.json and label.bib")
        try:
            from evid.core.bibtex import generate_bib_from_typ
            ok, msg = generate_bib_from_typ(str(typ_path))
            if not ok:
                logger.warning("BibTeX generation issue for %s: %s", doc_uuid, msg)
        except Exception:
            logger.exception("generate_bib_from_typ failed for %s", doc_uuid)

        # ── 6. Vector index ───────────────────────────────────────────────────
        p(6, n, "Indexing into vector store")
        doc = self._make_document(doc_dir, doc_uuid, doc_label, tags, source_type, source_url)
        if self.vec_service is not None:
            try:
                typ_text = typ_path.read_text(encoding="utf-8") if typ_path.exists() else ""
                self.vec_service.index_document(doc, typ_text, evidence_set)
                meta["indexed"] = True
            except Exception:
                logger.exception("VecService.index_document failed for %s", doc_uuid)

        # ── 7. Update evidmgr_meta.yml; mark anon_pending for anon sets ───────
        p(7, n, "Finalising metadata")
        from evidmgr.models import SetType
        if evidence_set.set_type == SetType.ANON:
            meta["anon_pending"] = True
        with (doc_dir / "evidmgr_meta.yml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True)

        logger.info("Ingested %s into set '%s'", doc_uuid, evidence_set.slug)
        return doc

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_document(
        self,
        doc_dir: Path,
        doc_uuid: str,
        label: str,
        tags: list[str],
        source_type: str,
        source_url: str,
    ) -> "Document":
        from evidmgr.models import Document, SourceType

        return Document(
            uuid=doc_uuid,
            path=doc_dir,
            label=label,
            tags=tags,
            source_type=SourceType(source_type),
            added=datetime.now(tz=timezone.utc),
            source_url=source_url,
        )

    def _load_existing(self, doc_dir: Path, doc_uuid: str) -> "Document":
        """Load a Document that was already ingested."""
        from evidmgr.models import Document, SourceType

        info_path = doc_dir / "info.yml"
        meta_path = doc_dir / "evidmgr_meta.yml"

        with info_path.open("r", encoding="utf-8") as f:
            info = yaml.safe_load(f) or {}
        meta = {}
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}

        tags_raw = info.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        return Document(
            uuid=doc_uuid,
            path=doc_dir,
            label=info.get("label", ""),
            tags=tags,
            source_type=SourceType(meta.get("source_type", "other")),
            added=datetime.now(tz=timezone.utc),
            indexed=meta.get("indexed", False),
            anon_pending=meta.get("anon_pending", False),
            notes=meta.get("notes", ""),
            source_url=info.get("url", ""),
        )
