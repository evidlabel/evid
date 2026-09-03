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
