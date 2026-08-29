"""ChromaDB client helper."""


def get_client(persist_directory: str):
    """Persistent Chroma client."""
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=persist_directory, settings=Settings(anonymized_telemetry=False)
    )
