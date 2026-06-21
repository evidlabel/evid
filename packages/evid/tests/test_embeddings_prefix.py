"""Tests for embedding model selection and e5 prefix logic (no model load)."""

import importlib

from evid.vec import embeddings


def test_env_var_overrides_config(monkeypatch):
    monkeypatch.setenv("EVID_EMBEDDING_MODEL", "some/custom-model")
    assert embeddings.model_name() == "some/custom-model"


def test_config_default_when_no_env(monkeypatch):
    monkeypatch.delenv("EVID_EMBEDDING_MODEL", raising=False)
    # Default config ships multilingual-e5-small.
    assert "e5" in embeddings.model_name()


def test_e5_prefixes():
    assert embeddings._query_prefix("intfloat/multilingual-e5-small") == "query: "
    assert embeddings._doc_prefix("intfloat/multilingual-e5-small") == "passage: "


def test_non_e5_has_no_prefix():
    assert embeddings._query_prefix("sentence-transformers/all-MiniLM-L6-v2") == ""
    assert embeddings._doc_prefix("BAAI/bge-m3") == ""


def test_module_imports_without_loading_model():
    # Importing must not pull in sentence-transformers / torch.
    importlib.reload(embeddings)
    assert embeddings._model is None
