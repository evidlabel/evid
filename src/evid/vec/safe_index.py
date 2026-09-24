"""Subprocess-isolated vector indexing.

ChromaDB initialization and sentence-transformers / onnxruntime can crash
natively (SIGSEGV) on some Linux setups. Running the indexing in a spawned
child process means a native crash kills the child, not the GUI.

Two paths share the same child code:

* :func:`index_in_subprocess` — one document, one short-lived child. Used for a
  single ad-hoc index.
* :class:`IndexWorkerPool` — one long-lived child that indexes many documents.
  The embedding model is loaded once (lazily, on the first job) and reused, so
  a batch of N documents pays the cold start once instead of N times.

The child is a real OS process (``subprocess``, not ``multiprocessing`` spawn)
so it does not share a GIL or Qt state with the GUI. It is niced and
thread-capped: indexing is never urgent and must not freeze a laptop.
"""

from __future__ import annotations

import contextlib
import json
import os
import selectors
import signal
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Self

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


def _index_one(
    vecdb_dir: str,
    doc_uuid: str,
    doc_label: str,
    doc_tags: list[str],
    typ_text: str,
) -> None:
    """Index a single document. Raises on Python-level failure."""
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
        _index_one(vecdb_dir, doc_uuid, doc_label, doc_tags, typ_text)
    except BaseException as exc:
        traceback.print_exc()
        print(f"[safe_index] FAILED for {doc_uuid}: {exc}", file=sys.stderr)
        sys.exit(2)


def _serve() -> int:
    """Long-lived child: read newline-delimited JSON jobs, reply per job.

    The embedding model is loaded lazily by the first job and stays warm for the
    life of the process, so a batch pays the cold start once. Stdin EOF (parent
    exit) ends the loop cleanly.
    """
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except ValueError as exc:
            _reply(ok=False, msg=f"bad job JSON: {exc}")
            continue
        if job.get("op") == "stop":
            break
        try:
            _index_one(
                job["vecdb"],
                job["uuid"],
                job.get("label", ""),
                job.get("tags", []),
                job.get("text", ""),
            )
            _reply(ok=True, msg="ok")
        except BaseException as exc:
            traceback.print_exc(file=sys.stderr)
            _reply(ok=False, msg=str(exc))
    return 0


def _reply(*, ok: bool, msg: str) -> None:
    sys.stdout.write(json.dumps({"ok": ok, "msg": msg}) + "\n")
    sys.stdout.flush()


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(_THREAD_ENV)
    return env


def _popen_low_priority(cmd: list[str], stdout: int) -> subprocess.Popen:
    """Spawn *cmd* niced, thread-capped, in its own session.

    *stdout* is ``subprocess.DEVNULL`` for the one-shot path (diagnostics come
    from stderr) or ``subprocess.PIPE`` for the long-lived ``--serve`` worker
    (jobs are answered on stdout).
    """
    if os.name == "posix":
        cmd = ["nice", "-n", str(_NICE_DELTA), *cmd]
    return subprocess.Popen(  # noqa: S603 — cmd is argv (nice + sys.executable -m)
        cmd,
        stdin=subprocess.PIPE,
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        env=_child_env(),
        start_new_session=True,
    )


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
    proc = _popen_low_priority(cmd, subprocess.DEVNULL)
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


class IndexWorkerPool:
    """One long-lived, niced child indexing jobs sequentially.

    The child loads the embedding model on its first job and keeps it warm, so
    indexing a batch of documents avoids N model cold starts. Thread-safe. Call
    :meth:`close` when the batch is done to release the child (and its vecdb
    file lock); it is also safe to keep open and reuse.
    """

    def __init__(self, timeout: float = 600.0) -> None:
        self._timeout = timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def _spawn(self) -> subprocess.Popen:
        return _popen_low_priority(
            [sys.executable, "-m", "evid.vec.safe_index", "--serve"],
            subprocess.PIPE,
        )

    def _ensure(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = self._spawn()
        return self._proc

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        with contextlib.suppress(Exception):
            if proc.stdin is not None:
                proc.stdin.close()  # EOF → child exits after the current job
        try:
            proc.wait(timeout=3)
        except Exception:
            _kill_group(proc)
        finally:
            with contextlib.suppress(Exception):
                if proc.stdout is not None:
                    proc.stdout.close()

    def close(self) -> None:
        with self._lock:
            self._stop()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> bool:
        self.close()
        return False

    # ── work ───────────────────────────────────────────────────────────────

    def index(
        self,
        vecdb_dir: str | Path,
        doc_uuid: str,
        doc_label: str,
        doc_tags: list[str],
        typ_text: str,
        timeout: float | None = None,
    ) -> tuple[bool, str]:
        """Index one document in the shared child. Restarts it if it died."""
        with self._lock:
            return self._index_locked(
                vecdb_dir, doc_uuid, doc_label, doc_tags, typ_text, timeout
            )

    def _index_locked(
        self,
        vecdb_dir: str | Path,
        doc_uuid: str,
        doc_label: str,
        doc_tags: list[str],
        typ_text: str,
        timeout: float | None,
    ) -> tuple[bool, str]:
        timeout = self._timeout if timeout is None else timeout
        Path(vecdb_dir).mkdir(parents=True, exist_ok=True)
        proc = self._ensure()
        payload = (
            json.dumps(
                {
                    "vecdb": str(vecdb_dir),
                    "uuid": doc_uuid,
                    "label": doc_label,
                    "tags": list(doc_tags),
                    "text": typ_text,
                }
            ).encode("utf-8")
            + b"\n"
        )
        try:
            assert proc.stdin is not None
            proc.stdin.write(payload)
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._stop()
            return False, f"index child unavailable: {exc}"

        line = self._read_line(proc, timeout)
        if line is None:
            self._stop()
            return False, f"timed out after {timeout}s"
        if line == "":
            self._stop()
            return False, "index child exited unexpectedly"
        try:
            reply = json.loads(line)
        except ValueError:
            self._stop()
            return False, f"bad reply from index child: {line[:200]!r}"
        return bool(reply.get("ok")), str(reply.get("msg", ""))

    @staticmethod
    def _read_line(proc: subprocess.Popen, timeout: float) -> str | None:
        """Read one reply line, or None on timeout. Empty string on EOF."""
        if proc.stdout is None:
            return ""
        sel = selectors.DefaultSelector()
        try:
            sel.register(proc.stdout, selectors.EVENT_READ)
            if not sel.select(timeout):
                return None
            return proc.stdout.readline().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            return ""
        finally:
            sel.close()


def index_in_subprocess(
    vecdb_dir: str | Path,
    doc_uuid: str,
    doc_label: str,
    doc_tags: list[str],
    typ_text: str,
    timeout: float = 600.0,
) -> tuple[bool, str]:
    """Index one document in a short-lived niced subprocess (one-shot)."""
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
    """CLI for ``python -m evid.vec.safe_index``.

    One-shot mode reads typ text from stdin and indexes the document named by
    ``--uuid``. ``--serve`` runs the long-lived batch worker instead.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="evid.vec.safe_index")
    parser.add_argument("--serve", action="store_true", help="long-lived batch worker")
    parser.add_argument("--vecdb")
    parser.add_argument("--uuid")
    parser.add_argument("--label", default="")
    parser.add_argument("--tags", default="")
    args = parser.parse_args(argv)

    if args.serve:
        return _serve()

    if not args.vecdb or not args.uuid:
        parser.error("--vecdb and --uuid are required (unless --serve)")
    typ_text = sys.stdin.read()
    tags = [t for t in args.tags.split(",") if t]
    _index_worker(args.vecdb, args.uuid, args.label, tags, typ_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
