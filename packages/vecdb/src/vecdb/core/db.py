"""ChromaDB operations with metadata support."""

from ..utils.embeddings import generate_embeddings


def get_client(persist_directory: str):
    """Persistent Chroma client."""
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=persist_directory, settings=Settings(anonymized_telemetry=False)
    )


def create_collection(client, collection_name: str = "default"):
    """Create collection."""
    return client.create_collection(collection_name)


def add_document(
    client,
    collection_name: str,
    document: str,
    doc_id: str,
    metadata: dict | None = None,
):
    """Add a single document."""
    bulk_add_documents(
        client, collection_name, [document], [doc_id], [metadata] if metadata else None
    )


def bulk_add_documents(
    client,
    collection_name: str,
    documents: list[str],
    ids: list[str],
    metadatas: list[dict] | None = None,
):
    """Vectorized bulk add with full metadata (title, url, etc)."""
    collection = client.get_collection(collection_name)
    batch_size = 2000
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i : i + batch_size]
        batch_ids = ids[i : i + batch_size]
        batch_embeddings = generate_embeddings(batch_docs)
        batch_metas = metadatas[i : i + batch_size] if metadatas else None
        collection.add(
            documents=batch_docs,
            embeddings=batch_embeddings,
            ids=batch_ids,
            metadatas=batch_metas,
        )


def query_collection(client, collection_name: str, query_text: str, n_results: int = 5):
    """Query (returns metadatas automatically)."""
    embedding = generate_embeddings([query_text])[0]
    collection = client.get_collection(collection_name)
    return collection.query(query_embeddings=[embedding], n_results=n_results)
