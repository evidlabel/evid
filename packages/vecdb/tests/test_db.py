"""Tests for ChromaDB operations."""

import pytest
import os
import shutil

try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False

try:
    from sentence_transformers import SentenceTransformer
    HAS_ST = True
except ImportError:
    HAS_ST = False

pytestmark = pytest.mark.skipif(
    not HAS_CHROMADB or not HAS_ST, reason="Missing chromadb or sentence-transformers"
)

from vecdb.core.db import get_client, create_collection, add_document, bulk_add_documents, query_collection


@pytest.fixture
def client():
    temp_path = "tests/temp_db"
    os.makedirs(temp_path, exist_ok=True)
    client = get_client(temp_path)
    yield client
    shutil.rmtree(temp_path)


def test_create_collection(client):
    """Test creating a collection."""
    collection = create_collection(client, "test_collection")
    assert isinstance(collection, chromadb.Collection)


def test_add_document(client):
    """Test adding a single document."""
    create_collection(client, "test_collection")
    add_document(client, "test_collection", "Test document", "test_id")
    results = query_collection(client, "test_collection", "Test document", n_results=1)
    assert len(results["ids"][0]) > 0


def test_bulk_add_documents(client):
    """Test adding multiple documents."""
    create_collection(client, "test_collection")
    documents = ["Doc1", "Doc2"]
    ids = ["id1", "id2"]
    bulk_add_documents(client, "test_collection", documents, ids)
    results = query_collection(client, "test_collection", "Doc1", n_results=1)
    assert len(results["ids"][0]) > 0


def test_query_collection(client):
    """Test querying a collection."""
    create_collection(client, "test_collection")
    add_document(client, "test_collection", "Test query document", "query_id")
    results = query_collection(client, "test_collection", "Test query", n_results=1)
    assert len(results["ids"][0]) > 0
