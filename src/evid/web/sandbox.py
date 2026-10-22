"""The Agent pane's sandbox: each set's terminal runs under bubblewrap with the other sets hidden.

An agent in the pane works on one evidence set: it starts in that set's folder, ``evid`` there
defaults to the set, and it needs its login, settings and the network. What it must not reach is
any other evidence set — another case's evidence. So the sandbox leaves the machine as it is and
only swaps each set bucket (``anon/``, ``plain/``, ``sets/``) for an empty directory, binding the
selected set back where it was so that labels and annotations written by ``evid`` land in the real
set.

A host that embeds the pane and has a stricter policy of its own (the workbench hides a case's
raw files and other cases too) sets ``EVID_TERM_WRAP`` to a command prefix run in front of the
shell. That wins over this policy: evid then only knows that the terminal is sandboxed.

``EVID_SANDBOX=0`` (or ``evid gui --no-sandbox``) turns this sandbox off; so does a machine without
bubblewrap, and the pane says which of the two it got.
"""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Callable
from pathlib import Path

from evid.services.layout import bucket_dirs

Wrap = Callable[[], tuple[list[str], dict]]


def external() -> list[str]:
    """The host's wrap words (``EVID_TERM_WRAP``), or [] when the host supplies none."""
    raw = os.environ.get("EVID_TERM_WRAP", "").strip()
    return shlex.split(raw) if raw else []


def enabled() -> bool:
    """A terminal is sandboxed: by the host's wrap, or by bubblewrap unless asked not to."""
    if os.environ.get("EVID_TERM_WRAP", "").strip():
        return True  # a bad value fails when a terminal starts, not here
    return (
        os.environ.get("EVID_SANDBOX", "1") != "0" and shutil.which("bwrap") is not None
    )


def how() -> str:
    """'host', 'bwrap', or '' when the pane is not sandboxed at all (for the page's badge)."""
    if os.environ.get("EVID_TERM_WRAP", "").strip():
        return "host"
    return "bwrap" if enabled() else ""


def bwrap_argv(set_dir: Path, data_dir: Path) -> list[str]:
    """The ``bwrap ... --`` prefix for one terminal of SET_DIR in the store at DATA_DIR.

    The machine is shared as it is (``--dev-bind / /``): the agent's config, its network and the
    set's own folder. Each set bucket is emptied first, then the selected set is bound back, so its
    files are the only ones a terminal can see under the store.
    """
    argv = [
        "bwrap",
        "--die-with-parent",
        "--unshare-pid",
        "--dev-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",  # noqa: S108 — the terminal's own scratch, not a secret
    ]
    for root in bucket_dirs(data_dir):
        argv += ["--tmpfs", str(root.resolve())]
    set_dir = Path(set_dir).resolve()
    if set_dir.is_dir():
        argv += ["--bind", str(set_dir), str(set_dir)]
    return [*argv, "--"]


def wrap(set_dir: Path, data_dir: Path, env: dict) -> Wrap | None:
    """The ``wrap`` hook for one terminal of SET_DIR: argv prefix and env, read at every start.

    A host's ``EVID_TERM_WRAP`` wins (it may know more than the store does). With no host wrap,
    the set is sandboxed unless asked not to. ``None`` means the terminal runs plainly.
    """
    words = (
        external()
    )  # a malformed value raises here: the shell must not run unsandboxed
    if words:

        def make_external() -> tuple[list[str], dict]:
            return list(words), {**env, "EVID_SANDBOXED": "1"}

        return make_external
    if not enabled():
        return None

    def make() -> tuple[list[str], dict]:
        return bwrap_argv(set_dir, data_dir), {**env, "EVID_SANDBOXED": "1"}

    return make
