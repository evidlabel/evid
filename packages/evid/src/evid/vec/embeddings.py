"""Utilities for generating embeddings."""

import numpy as np

model = None


def _load_model():
    """Load the model lazily."""
    global model
    if model is None:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
    return model


def generate_embedding(text: str) -> np.ndarray:
    """Generate an embedding for the given text using the model."""
    _load_model()
    return model.encode(text, show_progress_bar=False)


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """Generate embeddings for a list of texts using vectorized batch processing."""
    _load_model()
    return model.encode(texts, show_progress_bar=False)
