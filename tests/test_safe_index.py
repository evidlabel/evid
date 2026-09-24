"""Tests for evid.vec.safe_index — low-priority OS subprocess isolation.

Indexing must not freeze the GUI: the child is a real OS process (not
multiprocessing spawn), niced, and thread-capped. A native crash kills the
child only.
"""

from __future__ import annotations

import os
import sys

from evid.vec.safe_index import run_low_priority


def test_run_low_priority_success():
    ok, msg = run_low_priority(
        [sys.executable, "-c", "raise SystemExit(0)"], timeout=30
    )
    assert ok is True
    assert msg == "ok"


def test_run_low_priority_non_zero_exit():
    ok, msg = run_low_priority(
        [sys.executable, "-c", "raise SystemExit(3)"], timeout=30
    )
    assert ok is False
    assert "3" in msg


def test_run_low_priority_survives_sigsegv():
    ok, msg = run_low_priority(
        [
            sys.executable,
            "-c",
            "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)",
        ],
        timeout=30,
    )
    assert ok is False
    assert "signal" in msg.lower()


def test_run_low_priority_timeout():
    ok, msg = run_low_priority(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        timeout=1,
    )
    assert ok is False
    assert "timed out" in msg.lower()


def test_run_low_priority_caps_threads_and_nice():
    """Child must not saturate a laptop: one BLAS/torch thread, lowest CPU nice."""
    probe = (
        "import os, sys\n"
        "if os.environ.get('OMP_NUM_THREADS') != '1': sys.exit(11)\n"
        "if os.environ.get('MKL_NUM_THREADS') != '1': sys.exit(12)\n"
        "if os.environ.get('TORCH_NUM_THREADS') != '1': sys.exit(13)\n"
        "if os.environ.get('TOKENIZERS_PARALLELISM') != 'false': sys.exit(14)\n"
        "if os.nice(0) < 19: sys.exit(15)\n"
    )
    ok, msg = run_low_priority([sys.executable, "-c", probe], timeout=30)
    assert ok is True, msg


def test_module_main_feeds_stdin_to_worker(monkeypatch):
    """python -m evid.vec.safe_index reads typ text from stdin."""
    from evid.vec import safe_index

    recorded: dict = {}

    def _fake_worker(vecdb, uuid, label, tags, typ_text):
        recorded["vecdb"] = vecdb
        recorded["uuid"] = uuid
        recorded["label"] = label
        recorded["tags"] = tags
        recorded["typ_text"] = typ_text

    monkeypatch.setattr(safe_index, "_index_worker", _fake_worker)
    monkeypatch.setattr(
        sys, "stdin", __import__("io").StringIO("paragraph one\n\nparagraph two")
    )
    rc = safe_index.main(
        [
            "--vecdb",
            "/tmp/vec",
            "--uuid",
            "ab" * 16,
            "--label",
            "Report",
            "--tags",
            "case,psych",
        ]
    )
    assert rc == 0
    assert recorded["vecdb"] == "/tmp/vec"
    assert recorded["uuid"] == "ab" * 16
    assert recorded["label"] == "Report"
    assert recorded["tags"] == ["case", "psych"]
    assert recorded["typ_text"] == "paragraph one\n\nparagraph two"


def test_index_in_subprocess_runs_module_cli(tmp_path, monkeypatch):
    """Parent launches the niced module CLI; typ text goes on stdin."""
    from evid.vec import safe_index

    recorded: dict = {}

    def _fake_run(cmd, *, stdin=b"", timeout=600.0):
        recorded["cmd"] = cmd
        recorded["stdin"] = stdin
        recorded["timeout"] = timeout
        return True, "ok"

    monkeypatch.setattr(safe_index, "run_low_priority", _fake_run)
    ok, msg = safe_index.index_in_subprocess(
        tmp_path / "vecdb",
        "cd" * 16,
        "Memo",
        ["tag-a"],
        "base paragraphs here",
        timeout=12,
    )
    assert ok is True
    assert msg == "ok"
    assert recorded["cmd"][:3] == [sys.executable, "-m", "evid.vec.safe_index"]
    assert "--uuid" in recorded["cmd"]
    assert "cd" * 16 in recorded["cmd"]
    assert recorded["stdin"] == b"base paragraphs here"
    assert recorded["timeout"] == 12


# ── long-lived batch worker ────────────────────────────────────────────────────


def test_serve_processes_jobs_and_replies(monkeypatch, capsys):
    """`--serve` indexes each stdin job and answers with a JSON line."""
    import io
    import json

    from evid.vec import safe_index

    jobs = [
        {"vecdb": "/tmp/v", "uuid": "a" * 32, "label": "L", "tags": ["t"], "text": "b"},
        {"op": "stop"},
    ]
    seen: list = []
    monkeypatch.setattr(safe_index, "_index_one", lambda *a: seen.append(a))
    monkeypatch.setattr(
        sys, "stdin", io.StringIO("\n".join(json.dumps(j) for j in jobs))
    )

    rc = safe_index._serve()
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert seen
    assert seen[0][1] == "a" * 32
    assert json.loads(out) == {"ok": True, "msg": "ok"}


def test_serve_reports_failure_without_dying(monkeypatch, capsys):
    """A failed job yields ok:false but the child keeps serving."""
    import io
    import json

    from evid.vec import safe_index

    def _boom(*_a):
        raise RuntimeError("nope")

    monkeypatch.setattr(safe_index, "_index_one", _boom)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps({"vecdb": "/tmp/v", "uuid": "b" * 32, "text": "x"}) + "\n"
        ),
    )

    rc = safe_index._serve()
    reply = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert reply["ok"] is False
    assert "nope" in reply["msg"]


class _FakeProc:
    def __init__(self) -> None:
        import io

        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return 0


def test_pool_reuses_one_child_for_a_batch(monkeypatch):
    """N jobs go to a single spawned child (one model load, not N)."""
    from evid.vec.safe_index import IndexWorkerPool

    spawns: list[_FakeProc] = []

    def _spawn():
        proc = _FakeProc()
        spawns.append(proc)
        return proc

    monkeypatch.setattr(IndexWorkerPool, "_spawn", staticmethod(_spawn))
    monkeypatch.setattr(
        IndexWorkerPool,
        "_read_line",
        staticmethod(lambda _proc, _timeout: '{"ok": true, "msg": "ok"}'),
    )

    pool = IndexWorkerPool()
    for i in range(3):
        ok, msg = pool.index("/tmp/v", f"{i:032d}", "L", [], "text")
        assert ok is True
        assert msg == "ok"
    assert len(spawns) == 1
    pool.close()


def test_pool_respawns_after_child_dies(monkeypatch):
    """If the child exits, the next job starts a fresh one."""
    from evid.vec.safe_index import IndexWorkerPool

    spawns: list[_FakeProc] = []

    def _spawn():
        proc = _FakeProc()
        spawns.append(proc)
        return proc

    monkeypatch.setattr(IndexWorkerPool, "_spawn", staticmethod(_spawn))
    monkeypatch.setattr(
        IndexWorkerPool,
        "_read_line",
        staticmethod(lambda _proc, _timeout: ""),  # EOF → child died
    )

    pool = IndexWorkerPool()
    ok, _ = pool.index("/tmp/v", "a" * 32, "L", [], "text")
    assert ok is False
    ok, _ = pool.index("/tmp/v", "b" * 32, "L", [], "text")
    assert ok is False
    assert len(spawns) == 2
    pool.close()
