"""Tests for evid.vec.safe_index — subprocess isolation must catch native
crashes (SIGSEGV etc.) without taking the parent down."""

from __future__ import annotations

import os
import signal
import time

from evid.vec.safe_index import run_in_subprocess


def _crash() -> None:
    os.kill(os.getpid(), signal.SIGSEGV)


def _noop() -> None:
    return None


def _raise() -> None:
    raise RuntimeError("simulated indexing failure")


def _hang() -> None:
    time.sleep(60)


def test_run_in_subprocess_survives_sigsegv():
    ok, msg = run_in_subprocess(_crash, (), timeout=30)
    assert ok is False
    assert "signal" in msg.lower()


def test_run_in_subprocess_python_error():
    ok, msg = run_in_subprocess(_raise, (), timeout=30)
    assert ok is False
    # multiprocessing returns 1 for an uncaught exception
    assert "exit" in msg.lower() or "signal" in msg.lower()


def test_run_in_subprocess_success():
    ok, msg = run_in_subprocess(_noop, (), timeout=30)
    assert ok is True
    assert msg == "ok"


def test_run_in_subprocess_timeout():
    ok, msg = run_in_subprocess(_hang, (), timeout=2)
    assert ok is False
    assert "timed out" in msg.lower()
