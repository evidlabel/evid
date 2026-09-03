"""Subprocess-isolated vector indexing.

ChromaDB initialization and sentence-transformers / onnxruntime can crash
natively (SIGSEGV) on some Linux setups. Running the indexing in a spawned
child process means a native crash kills the child, not the GUI.

The child is a real OS process (``subprocess``, not ``multiprocessing`` spawn)
so it does not share a GIL or Qt state with the GUI. It is niced and
thread-capped: indexing is never urgent and must not freeze a laptop.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import traceback
from pathlib import Path

# Cap BLAS / torch / tokenizers in the child so embedding cannot saturate
# every core. "1" is the point: indexing has no deadline.
_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "TORCH_NUM_THREADS": "1",
    "TOKENIZERS_PARALLELISM": "false",
}

_NICE_DELTA = 19


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


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(_THREAD_ENV)
    return env


def run_low_priority(
    cmd: list[str],
    *,
    stdin: bytes = b"",
    timeout: float = 600.0,
) -> tuple[bool, str]:
    """Run *cmd* in a niced, thread-capped OS subprocess.

    Returns ``(ok, message)``. A native crash or non-zero exit is ``ok=False``;
    the parent stays up. Call from a worker thread — this blocks until the
    child exits (or *timeout* seconds elapse).

    Niceness is applied via the ``nice`` executable rather than ``preexec_fn``,
    which can deadlock in a multithreaded Qt process.
    """
    if os.name == "posix":
        cmd = ["nice", "-n", str(_NICE_DELTA), *cmd]
    proc = subprocess.Popen(  # noqa: S603 — cmd is argv (nice + sys.executable -m)
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=_child_env(),
        start_new_session=True,
    )
    try:
        try:
            _, err = proc.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.communicate()
            return False, f"timed out after {timeout}s"
    except Exception as exc:
        _kill_group(proc)
        return False, str(exc)

    code = proc.returncode
    if code == 0:
        return True, "ok"
    if code is not None and code < 0:
        return False, f"subprocess killed by signal {-code}"
    detail = (err or b"").decode("utf-8", errors="replace").strip()
    if detail:
        return False, f"subprocess exited with code {code}: {detail}"
    return False, f"subprocess exited with code {code}"


def _kill_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        proc.kill()


def index_in_subprocess(
    vecdb_dir: str | Path,
    doc_uuid: str,
    doc_label: str,
    doc_tags: list[str],
    typ_text: str,
    timeout: float = 600.0,
) -> tuple[bool, str]:
    """Run :func:`_index_worker` in a niced OS subprocess via this module's CLI."""
    Path(vecdb_dir).mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "evid.vec.safe_index",
        "--vecdb",
        str(vecdb_dir),
        "--uuid",
        doc_uuid,
        "--label",
        doc_label,
        "--tags",
        ",".join(doc_tags),
    ]
    return run_low_priority(
        cmd,
        stdin=typ_text.encode("utf-8"),
        timeout=timeout,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI for ``python -m evid.vec.safe_index``. Typ text is read from stdin."""
    import argparse

    parser = argparse.ArgumentParser(prog="evid.vec.safe_index")
    parser.add_argument("--vecdb", required=True)
    parser.add_argument("--uuid", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--tags", default="")
    args = parser.parse_args(argv)
    typ_text = sys.stdin.read()
    tags = [t for t in args.tags.split(",") if t]
    _index_worker(args.vecdb, args.uuid, args.label, tags, typ_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
