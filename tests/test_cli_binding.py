"""The command tree must bind before evid starts.

treeparse checks each callback against its arguments when the parser is
built. That is the first thing `evid` does, so a mismatch used to show up
only as `make web` exiting.
"""

from __future__ import annotations

import subprocess
import sys


def test_command_tree_binds():
    from evid.cli.main import app

    app._validate()


def test_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "evid.cli.main", "-h"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "doc" in result.stdout
    assert "add" in result.stdout
    assert "screenshot" in result.stdout
