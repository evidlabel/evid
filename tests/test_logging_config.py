"""Tests for central logging configuration."""

import logging

from rich.logging import RichHandler

from evid.logging_config import _state, configure_logging


def test_configure_logging_quiets_noisy_libraries():
    configure_logging(verbose=False)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("chromadb").level == logging.WARNING
    # Pure-advisory libraries are clamped harder (HF-token nag, model load report).
    assert logging.getLogger("huggingface_hub").level == logging.ERROR
    assert logging.getLogger("transformers").level == logging.ERROR
    # Root stays at WARNING so libraries are quiet unless they truly warn.
    assert logging.getLogger().level == logging.WARNING
    # evid namespace is quiet on the happy path; --verbose / EVID_LOG_LEVEL for more.
    assert logging.getLogger("evid").level == logging.WARNING


def test_configure_logging_verbose_enables_debug():
    configure_logging(verbose=True)
    assert logging.getLogger("evid").level == logging.DEBUG
    # Noisy libraries stay clamped even in verbose mode.
    assert logging.getLogger("httpx").level == logging.WARNING
    configure_logging(verbose=False)
    assert logging.getLogger("evid").level == logging.WARNING


def test_configure_logging_sets_progress_bar_env():
    import os

    configure_logging()
    assert os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS") == "1"
    assert os.environ.get("TOKENIZERS_PARALLELISM") == "false"


def test_configure_logging_replaces_import_time_rich_handler():
    """Import-time basicConfig used to leave a RichHandler with INFO:name:msg."""
    root = logging.getLogger()
    leftover = RichHandler(rich_tracebacks=True)
    root.addHandler(leftover)
    _state["configured"] = False
    try:
        configure_logging(verbose=False)
        assert leftover not in root.handlers
        ours = [h for h in root.handlers if isinstance(h, RichHandler)]
        assert ours
        record = logging.LogRecord(
            "evid.core.text_cleaning",
            logging.INFO,
            __file__,
            1,
            "hello",
            (),
            None,
        )
        assert ours[0].format(record) == "hello"
    finally:
        leftover.close()
