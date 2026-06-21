"""evid MCP server — a warm, single-dataset query session for agents.

Each `evid search vec` CLI call is a fresh process that re-imports torch and
reloads the embedding model (~10 s cold start), which discourages running
sequences of queries. This stdio MCP server loads the model **once** and keeps
the Chroma clients warm, so every tool call after startup is sub-second.

**Scoped to one dataset.** The server is bound at startup to a single evidence
set and every tool operates only on it — there is no `list_sets` and no
`dataset` parameter. An attached agent therefore cannot discover or reach other
(possibly private) sets in the same data directory.

Run it (pointed at a database, scoped to one set) with:

    evid -d ./evid mcp my-case

and register that command as a stdio MCP server in your agent.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolved once in build_server(); shared so the embedding model and Chroma
# clients stay warm across calls. The server only ever touches _SET.
_SET = None  # EvidenceSet the server is bound to
_VEC = None  # VecService


def _vec_service():
    global _VEC
    if _VEC is None:
        from evid.services.vec_service import VecService

        _VEC = VecService()
    return _VEC


def _resolve_set(data_dir: Path, dataset: str):
    """Resolve one set by slug, falling back to a case-insensitive name match."""
    from evid.services.set_manager import SetManager

    sm = SetManager(data_dir)
    try:
        return sm.load_set(dataset)
    except FileNotFoundError:
        pass
    wanted = dataset.strip().lower()
    for s in sm.list_sets():
        if s.name.lower() == wanted or s.slug.lower() == wanted:
            return sm.load_set(s.slug)
    msg = f"Dataset '{dataset}' not found in {data_dir}."
    raise ValueError(msg)


def build_server(data_dir: Path, dataset: str):
    """Construct the FastMCP server bound to a single *dataset* in *data_dir*."""
    global _SET
    _SET = _resolve_set(Path(data_dir), dataset)

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(f"evid:{_SET.slug}")

    @mcp.tool()
    def search_vec(query: str, n: int = 10, tag: str = "") -> str:
        """Semantic vector search over this server's dataset. Returns the top-n
        matching chunks as JSON: score (cosine, higher=better), label, uuid,
        chunk_idx, char_start, preview. Primary discovery tool; the model stays
        warm across calls in this session."""
        results = _vec_service().query(
            _SET, query, n_results=n, filter_tags=[tag] if tag else None
        )
        out = [
            {
                "score": round(float(r.score), 4),
                "label": r.doc.label,
                "uuid": r.doc.uuid,
                "chunk_idx": r.chunk_idx,
                "char_start": r.char_start,
                "preview": r.chunk_text[:400],
            }
            for r in results
        ]
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    def search_text(query: str, regex: bool = False, n: int = 10) -> str:
        """Full-text search over document *bodies* in this dataset. Default is a
        fuzzy (rapidfuzz) match ranked per document; set regex=True to return
        every regex match. Returns JSON: uuid, label, page, char_start, score
        (fuzzy ratio or null), snippet."""
        from evid.core.fulltext import search_fulltext

        hits = search_fulltext(_SET.path, query, regex=regex, n=n)
        out = [
            {
                "uuid": h.uuid,
                "label": h.label,
                "page": h.page,
                "char_start": h.char_start,
                "score": h.score,
                "snippet": h.snippet,
            }
            for h in hits
        ]
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    def search_meta(pattern: str) -> str:
        """Regex/substring search over document metadata (info.yml fields) in
        this dataset. Returns JSON: uuid, label, tags."""
        from evid.core.doc_loader import search_meta_documents

        docs = search_meta_documents(_SET.path, pattern)
        out = [{"uuid": d.uuid, "label": d.label, "tags": d.tags} for d in docs]
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    def list_docs() -> str:
        """List documents in this dataset as JSON: uuid, label, tags."""
        from evid.core.doc_loader import search_meta_documents

        docs = search_meta_documents(_SET.path, "")
        out = [{"uuid": d.uuid, "label": d.label, "tags": d.tags} for d in docs]
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    def doc_quotes(uuid: str) -> str:
        """Return a document's labelled citations (`#lab` spans) rendered as
        Markdown, or a note if the document has no labels yet."""
        from evid.core.prompt import quotes_markdown

        md = quotes_markdown([_SET.path / "docs" / uuid])
        return md or "(no citations — document not yet labelled)"

    return mcp


def serve(data_dir: Path, dataset: str) -> None:
    """Run the evid MCP server on stdio for one *dataset* (blocks)."""
    server = build_server(data_dir, dataset)
    logger.info("Starting evid MCP server for set '%s' on %s", _SET.slug, data_dir)
    server.run(transport="stdio")
