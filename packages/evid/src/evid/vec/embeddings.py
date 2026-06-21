"""Embedding generation for vector search.

The model is configurable via ``EvidConfig.embedding_model`` (or the
``EVID_EMBEDDING_MODEL`` env var, which wins). Default:
``intfloat/multilingual-e5-small`` — multilingual (strong on Danish),
384-dim, MIT-licensed.

**Asymmetric prefixes.** e5 models require ``"query: "`` on search queries and
``"passage: "`` on indexed documents; mixing them up degrades retrieval. Use
``embed_query`` for queries and ``embed_documents`` for indexed text — they
apply the right prefix for the active model (and no prefix for non-e5 models).

Switching models invalidates existing vector indexes (embeddings from two
models are not comparable). After changing the model, run ``evid set reindex``
on each set.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

_model = None
_loaded_name: str | None = None


def model_name() -> str:
    """Active embedding model id (env var wins over config)."""
    env = os.environ.get("EVID_EMBEDDING_MODEL")
    if env:
        return env
    from evid.config import EvidConfig

    return EvidConfig.load().embedding_model


def _load_model():
    """Load (and cache) the active model, reloading if the name changed."""
    global _model, _loaded_name
    name = model_name()
    if _model is None or _loaded_name != name:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(name)
        _loaded_name = name
    return _model


def _is_e5(name: str) -> bool:
    return "e5" in name.lower()


def _query_prefix(name: str) -> str:
    return "query: " if _is_e5(name) else ""


def _doc_prefix(name: str) -> str:
    return "passage: " if _is_e5(name) else ""


def embed_documents(texts: list[str]) -> np.ndarray:
    """Embed indexed document chunks (applies the document prefix)."""
    model = _load_model()
    prefix = _doc_prefix(_loaded_name)
    payload = [prefix + t for t in texts] if prefix else texts
    return model.encode(payload, show_progress_bar=False, normalize_embeddings=True)


def embed_query(text: str) -> np.ndarray:
    """Embed a single search query (applies the query prefix)."""
    model = _load_model()
    prefix = _query_prefix(_loaded_name)
    return model.encode(
        prefix + text, show_progress_bar=False, normalize_embeddings=True
    )
