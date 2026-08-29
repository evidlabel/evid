"""Central logging configuration for the evid CLI.

Historically the CLI called ``logging.basicConfig(level=DEBUG)`` at import time,
which pinned the *root* logger to DEBUG. Every third-party library (httpx,
huggingface_hub, sentence_transformers, chromadb, urllib3, …) then dumped its
INFO/DEBUG chatter — plus progress bars — into the terminal, drowning the actual
command output (notably ``search vec`` and ``doc add``).

``configure_logging`` replaces that: the evid namespace logs at INFO (DEBUG with
``--verbose`` / ``EVID_LOG_LEVEL``), noisy libraries are clamped to WARNING, and
the model-download/encode progress bars are disabled via environment variables.
"""

from __future__ import annotations

import logging
import os

from rich.logging import RichHandler

# Third-party loggers that otherwise flood the terminal at INFO/DEBUG.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "sentence_transformers",
    "chromadb",
    "urllib3",
    "filelock",
    "fsspec",
)

# These emit only advisory noise on the happy path (HF-token nag, model-load
# reports), so clamp them harder — to ERROR.
_ADVISORY_LOGGERS = ("huggingface_hub", "transformers")

_state = {"configured": False}


def configure_logging(*, verbose: bool = False) -> None:
    """Configure logging once for a CLI run.

    Args:
        verbose: When True (``-v``/``--verbose``), the evid namespace logs at
            DEBUG. Otherwise the level comes from ``EVID_LOG_LEVEL`` (default
            INFO). The root logger stays at WARNING so third-party libraries are
            quiet unless they emit a genuine warning/error.
    """
    # Silence progress bars / advisory spam from the embedding stack. Set before
    # those libraries are imported (imports are lazy, inside vec_service), so the
    # environment is already in place when they load.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    # Verbosity knobs read by huggingface_hub / transformers themselves — these
    # silence the HF-token nag and the model "LOAD REPORT" that bypass our logger
    # config via their own handlers.
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

    evid_level = (
        logging.DEBUG
        if verbose
        else getattr(
            logging, os.environ.get("EVID_LOG_LEVEL", "INFO").upper(), logging.INFO
        )
    )

    if not _state["configured"]:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(message)s",
            handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
        )
        _state["configured"] = True

    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("evid").setLevel(evid_level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in _ADVISORY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)
