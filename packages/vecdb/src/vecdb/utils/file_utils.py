"""Utilities for discovering label.typ files and loading metadata from info.yml."""

import glob
import os
from pathlib import Path

from ..models.info import DocumentInfo


def get_label_files(directory: str) -> list[str]:
    """Return all label.typ files (as per current dataset assumption)."""
    return glob.glob(os.path.join(directory, "**", "label.typ"), recursive=True)


def load_info_yml(label_path: str) -> DocumentInfo:
    """Load sibling info.yml and validate with Pydantic."""
    info_path = Path(label_path).parent / "info.yml"
    if not info_path.exists():
        # fallback
        return DocumentInfo(
            title=Path(label_path).parent.name, uuid=Path(label_path).parent.name
        )
    import yaml

    with open(info_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return DocumentInfo.model_validate(data)


def snippetize_document(file_path: str) -> list[str]:
    """Split into paragraphs (works great for Typst label.typ)."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    return [p.strip() for p in content.split("\n\n") if p.strip()]


def get_documents_with_metadata(
    target_dir: str,
) -> tuple[list[str], list[dict], list[str]]:
    """Helper: returns (documents, metadatas, ids) ready for bulk add."""
    label_files = get_label_files(target_dir)
    documents = []
    metadatas = []
    ids = []
    for file_path in label_files:
        info = load_info_yml(file_path)
        chunks = snippetize_document(file_path)
        for i, chunk in enumerate(chunks, 1):
            chunk_id = f"{info.uuid}_{i:04d}"
            meta = info.model_dump(exclude_none=True)
            meta["source"] = os.path.relpath(file_path)
            meta["chunk"] = i
            documents.append(chunk)
            metadatas.append(meta)
            ids.append(chunk_id)
    return documents, metadatas, ids
