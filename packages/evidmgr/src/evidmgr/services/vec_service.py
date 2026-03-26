"""VecService — per-set ChromaDB client wrapping vecdb."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evidmgr.models import Document, EvidenceSet, VecResult

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "docs"


class VecService:
    """One ChromaDB PersistentClient per EvidenceSet, opened lazily."""

    def __init__(self) -> None:
        self._clients: dict[str, object] = {}  # slug → chromadb.PersistentClient

    def _client(self, evidence_set: "EvidenceSet") -> object:
        slug = evidence_set.slug
        if slug not in self._clients:
            from vecdb.core.db import get_client
            vecdb_dir = evidence_set.path / "vecdb"
            vecdb_dir.mkdir(exist_ok=True)
            self._clients[slug] = get_client(str(vecdb_dir))
        return self._clients[slug]

    def _collection(self, evidence_set: "EvidenceSet") -> object:
        client = self._client(evidence_set)
        try:
            return client.get_collection(_COLLECTION_NAME)
        except Exception:
            return client.create_collection(_COLLECTION_NAME)

    def close(self, slug: str) -> None:
        """Release the ChromaDB client for a set (frees file lock)."""
        self._clients.pop(slug, None)

    # ── indexing ──────────────────────────────────────────────────────────────

    def index_document(
        self, doc: "Document", typ_text: str, evidence_set: "EvidenceSet"
    ) -> None:
        """Chunk *typ_text* and upsert into the set's ChromaDB collection."""
        from vecdb.utils.embeddings import generate_embeddings

        chunks = self._chunk(typ_text)
        if not chunks:
            logger.warning("No chunks for document %s", doc.uuid)
            return

        collection = self._collection(evidence_set)
        ids = [f"{doc.uuid}:{i}" for i in range(len(chunks))]
        char_starts = self._char_starts(typ_text, chunks)
        metadatas = [
            {
                "doc_uuid": doc.uuid,
                "label": doc.label,
                "tags": ",".join(doc.tags),
                "source_type": str(doc.source_type),
                "chunk_idx": i,
                "char_start": char_starts[i],
            }
            for i in range(len(chunks))
        ]

        # Delete any existing chunks for this doc before re-indexing
        try:
            collection.delete(where={"doc_uuid": doc.uuid})
        except Exception:
            pass  # collection may be empty

        embeddings = generate_embeddings(chunks)
        collection.add(
            documents=chunks,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas,
        )
        logger.info("Indexed %d chunks for %s in set '%s'", len(chunks), doc.uuid, evidence_set.slug)

    def remove_document(self, doc_uuid: str, evidence_set: "EvidenceSet") -> None:
        collection = self._collection(evidence_set)
        try:
            collection.delete(where={"doc_uuid": doc_uuid})
        except Exception:
            logger.exception("Failed to remove %s from vecdb", doc_uuid)

    # ── querying ──────────────────────────────────────────────────────────────

    def query(
        self,
        evidence_set: "EvidenceSet",
        query_text: str,
        n_results: int = 10,
        filter_tags: list[str] | None = None,
        filter_source_type: str = "",
    ) -> list["VecResult"]:
        from vecdb.utils.embeddings import generate_embeddings
        from evidmgr.models import Document, SourceType, VecResult

        collection = self._collection(evidence_set)
        where: dict | None = None
        if filter_source_type:
            where = {"source_type": {"$eq": filter_source_type}}

        embedding = generate_embeddings([query_text])[0]
        results = collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
        )

        vec_results = []
        docs_cache: dict[str, Document] = {}
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            chunk_text = results["documents"][0][i]
            doc_uuid = meta["doc_uuid"]

            # Tag filter is applied client-side (ChromaDB doesn't support array contains)
            if filter_tags:
                doc_tags = set(t.strip() for t in meta.get("tags", "").split(",") if t.strip())
                if not doc_tags.issuperset(filter_tags):
                    continue

            if doc_uuid not in docs_cache:
                doc_dir = evidence_set.path / "docs" / doc_uuid
                docs_cache[doc_uuid] = self._load_document(doc_dir, doc_uuid)

            vec_results.append(
                VecResult(
                    doc=docs_cache[doc_uuid],
                    chunk_text=chunk_text,
                    score=1.0 - distance,  # cosine distance → similarity
                    chunk_idx=meta.get("chunk_idx", 0),
                    char_start=meta.get("char_start", 0),
                )
            )
        return vec_results

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _chunk(text: str) -> list[str]:
        return [p.strip() for p in text.split("\n\n") if p.strip()]

    @staticmethod
    def _char_starts(text: str, chunks: list[str]) -> list[int]:
        starts = []
        pos = 0
        for chunk in chunks:
            idx = text.find(chunk, pos)
            starts.append(max(idx, 0))
            pos = idx + len(chunk) if idx >= 0 else pos
        return starts

    @staticmethod
    def _load_document(doc_dir: Path, doc_uuid: str) -> "Document":
        import yaml
        from datetime import datetime, timezone
        from evidmgr.models import Document, SourceType

        info_path = doc_dir / "info.yml"
        meta_path = doc_dir / "evidmgr_meta.yml"

        info = {}
        if info_path.exists():
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
            label=info.get("label", doc_uuid),
            tags=tags,
            source_type=SourceType(meta.get("source_type", "other")),
            added=datetime.now(tz=timezone.utc),
            indexed=meta.get("indexed", False),
            anon_pending=meta.get("anon_pending", False),
            notes=meta.get("notes", ""),
            source_url=info.get("url", ""),
        )
