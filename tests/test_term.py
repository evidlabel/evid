"""The Agent pane's terminals: the sandbox hook and the argv it builds.

No bubblewrap is run here: the prefix is asserted as text, and the hook is exercised with a
plain ``env`` in front of the shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from evid.web import sandbox
from evid.web.term import Sessions, Terminal

if TYPE_CHECKING:
    from pathlib import Path


def _terminal(tmp_path: Path, wrap=None) -> Terminal:
    env = {"SHELL": "/bin/sh", "PATH": "/usr/bin:/bin", "PS1": "$ "}
    return Terminal(str(tmp_path), env, agent="", wrap=wrap)


def test_the_set_buckets_are_emptied_and_the_set_bound_back(tmp_path):
    data = tmp_path / "data"
    anon = data / "anon" / "anon_set_case"
    plain = data / "plain" / "plain_set_other"
    anon.mkdir(parents=True)
    plain.mkdir(parents=True)
    (data / "sets").mkdir(parents=True)

    argv = sandbox.bwrap_argv(anon, data)

    assert argv[0] == "bwrap" and argv[-1] == "--"
    for root in (data / "anon", data / "plain", data / "sets"):
        assert ["--tmpfs", str(root)] == argv[
            argv.index(str(root)) - 1 : argv.index(str(root)) + 1
        ]
    assert argv[argv.index(str(anon)) - 1 : argv.index(str(anon)) + 2] == [
        "--bind",
        str(anon),
        str(anon),
    ]
    assert str(plain) not in argv  # another set is not bound back


def test_the_store_is_shared_when_there_are_no_buckets(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    set_dir = tmp_path / "outside" / "case"
    set_dir.mkdir(parents=True)

    argv = sandbox.bwrap_argv(set_dir, data)

    assert argv.count("--tmpfs") == 1 and "/tmp" in argv  # only the private /tmp
    assert argv[argv.index(str(set_dir)) - 1 : argv.index(str(set_dir)) + 2] == [
        "--bind",
        str(set_dir),
        str(set_dir),
    ]


def test_wrap_is_off_when_asked(tmp_path, monkeypatch):
    monkeypatch.delenv("EVID_TERM_WRAP", raising=False)
    monkeypatch.setenv("EVID_SANDBOX", "0")
    assert not sandbox.enabled()
    assert sandbox.how() == ""
    assert sandbox.wrap(tmp_path, tmp_path, {"SHELL": "/bin/sh"}) is None


def test_a_host_wrap_wins_over_the_store_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("EVID_TERM_WRAP", "/usr/bin/env jura-sandbox")
    assert sandbox.enabled() and sandbox.how() == "host"
    make = sandbox.wrap(tmp_path, tmp_path, {"SHELL": "/bin/sh"})
    prefix, env = make()
    assert prefix == ["/usr/bin/env", "jura-sandbox"]  # the host's words, not bwrap
    assert env["EVID_SANDBOXED"] == "1"


def test_a_malformed_host_wrap_does_not_run_the_shell_plainly(tmp_path, monkeypatch):
    monkeypatch.setenv("EVID_TERM_WRAP", "'")  # unbalanced quote
    assert sandbox.enabled()  # the page still says "sandbox"
    with pytest.raises(ValueError):
        sandbox.wrap(tmp_path, tmp_path, {"SHELL": "/bin/sh"})()


def test_wrap_prefix_is_read_at_every_start(tmp_path):
    def wrap():
        return ["env"], {
            "SHELL": "/bin/sh",
            "PATH": "/usr/bin:/bin",
            "EVID_SANDBOXED": "1",
        }

    term = _terminal(tmp_path, wrap)
    try:
        assert not term.sandboxed
        term.start()
        assert term.sandboxed
        assert term.proc.args == ["env", "/bin/sh", "-i"]
    finally:
        term.stop()
    assert not term.alive


def test_a_plain_terminal_is_not_sandboxed(tmp_path):
    term = _terminal(tmp_path)
    try:
        term.start()
        assert not term.sandboxed
        assert term.proc.args == ["/bin/sh", "-i"]
    finally:
        term.stop()


def test_sessions_report_sandboxed(tmp_path):
    terms = Sessions(str(tmp_path), {"SHELL": "/bin/sh"}, None)
    sid = terms.add("")
    try:
        assert terms.list()[0]["sandboxed"] is False
        assert terms.list()[0]["id"] == sid
    finally:
        terms.stop()


def test_set_agents_hand_the_sandbox_to_each_set(tmp_path, monkeypatch):
    from evid.web.server import SetAgents

    class Set:
        slug = "case"

        def __init__(self, path):
            self.path = path

    set_dir = tmp_path / "data" / "anon" / "anon_set_case"
    set_dir.mkdir(parents=True)
    monkeypatch.setattr(sandbox, "enabled", lambda: True)
    agents = SetAgents(tmp_path / "data", "http://127.0.0.1:1/", "")
    try:
        terms = agents.get(Set(set_dir))
        assert terms is not None and terms.wrap is not None
        prefix, _env = terms.wrap()
        assert prefix[0] == "bwrap" and str(set_dir) in prefix
    finally:
        agents.stop()


def test_set_agents_leave_the_pane_plain_when_the_sandbox_is_off(tmp_path, monkeypatch):
    from evid.web.server import SetAgents

    class Set:
        slug = "case"

        def __init__(self, path):
            self.path = path

    set_dir = tmp_path / "data" / "anon" / "anon_set_case"
    set_dir.mkdir(parents=True)
    monkeypatch.setenv("EVID_SANDBOX", "0")
    agents = SetAgents(tmp_path / "data", "http://127.0.0.1:1/", "")
    try:
        terms = agents.get(Set(set_dir))
        assert terms is not None and terms.wrap is None
    finally:
        agents.stop()
