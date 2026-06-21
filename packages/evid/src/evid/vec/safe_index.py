"""Subprocess-isolated vector indexing.

ChromaDB initialization and sentence-transformers / onnxruntime can crash
natively (SIGSEGV) on some Linux setups. Running the indexing in a spawned
child process means a native crash kills the child, not the GUI.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import sys
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)


def _index_worker(
    vecdb_dir: str,
    doc_uuid: str,
    doc_label: str,
    doc_tags: list[str],
    typ_text: str,
) -> None:
    """Run inside the spawned child. Exit non-zero on Python-level failure;
    a native crash here cannot escape to the parent."""
    try:
        from evid.vec.chunking import chunk_text
        from evid.vec.db import get_client
        from evid.vec.embeddings import embed_documents, model_name

        pairs = chunk_text(typ_text)
        if not pairs:
            print(f"[safe_index] No chunks for {doc_uuid}", file=sys.stderr)
            return
        chunks = [c for c, _ in pairs]
        char_starts = [s for _, s in pairs]

        client = get_client(vecdb_dir)
        try:
            collection = client.get_collection("docs")
        except Exception:
            collection = client.create_collection("docs")
        try:
            collection.modify(metadata={"embedding_model": model_name()})
        except Exception:
            pass

        ids = [f"{doc_uuid}:{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "doc_uuid": doc_uuid,
                "label": doc_label,
                "tags": ",".join(doc_tags),
                "chunk_idx": i,
                "char_start": char_starts[i],
            }
            for i in range(len(chunks))
        ]

        try:
            collection.delete(where={"doc_uuid": doc_uuid})
        except Exception:
            pass

        embeddings = embed_documents(chunks)
        batch = 2000
        for start in range(0, len(chunks), batch):
            end = start + batch
            collection.add(
                documents=chunks[start:end],
                embeddings=embeddings[start:end],
                ids=ids[start:end],
                metadatas=metadatas[start:end],
            )

        print(
            f"[safe_index] Indexed {len(chunks)} chunks for {doc_uuid}",
            file=sys.stderr,
        )
    except BaseException as exc:
        traceback.print_exc()
        print(f"[safe_index] FAILED for {doc_uuid}: {exc}", file=sys.stderr)
        sys.exit(2)


def run_in_subprocess(
    target, args: tuple, timeout: float = 600.0, name: str = "vec-worker"
) -> tuple[bool, str]:
    """Run *target* in a spawned subprocess, returning ``(ok, message)``.

    A native crash (SIGSEGV etc.) yields ``ok=False`` with the signal number;
    a Python-level error yields a non-zero exit code; the parent stays up.
    """
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=target, args=args, name=name)
    proc.start()
    proc.join(timeout=timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        return False, f"timed out after {timeout}s"

    code = proc.exitcode
    if code == 0:
        return True, "ok"
    if code is not None and code < 0:
        return False, f"subprocess killed by signal {-code}"
    return False, f"subprocess exited with code {code}"


def index_in_subprocess(
    vecdb_dir: str | Path,
    doc_uuid: str,
    doc_label: str,
    doc_tags: list[str],
    typ_text: str,
    timeout: float = 600.0,
) -> tuple[bool, str]:
    """Run :func:`_index_worker` in a spawned subprocess."""
    Path(vecdb_dir).mkdir(parents=True, exist_ok=True)
    return run_in_subprocess(
        _index_worker,
        (str(vecdb_dir), doc_uuid, doc_label, list(doc_tags), typ_text),
        timeout=timeout,
        name=f"vec-index-{doc_uuid[:8]}",
    )
