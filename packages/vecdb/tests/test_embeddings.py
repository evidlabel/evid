"""Tests for embedding utilities."""

import numpy as np
import pytest
from vecdb.utils.embeddings import generate_embedding

try:
    from sentence_transformers import SentenceTransformer

    HAS_ST = True
except ImportError:
    HAS_ST = False

pytestmark = pytest.mark.skipif(
    not HAS_ST, reason="sentence-transformers not installed"
)


def test_generate_embedding():
    """Test generating an embedding."""
    embedding = generate_embedding("Test text")
    assert isinstance(embedding, np.ndarray)  # Check type
    assert embedding.shape[0] > 0  # Should have dimension
    assert isinstance(
        embedding[0], np.float32
    )  # Elements are floats (note: may be float32)
