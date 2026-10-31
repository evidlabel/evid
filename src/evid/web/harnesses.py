"""The agent harnesses the Agent pane offers.

The pane runs a terminal per evidence set and types one command into it (see
``term.Terminal``), so a harness is a command. This module decides which
commands are worth offering: the agent CLIs installed on this machine, the
saved OpenCode profiles, and whatever ``--agent`` / ``$EVID_AGENT`` says first.
The page turns each into one click; nothing here starts a process.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# id, label, command. Installed when the command's first word is on PATH.
CATALOG: tuple[tuple[str, str, str], ...] = (
    ("claude", "Claude Code", "claude"),
    ("codex", "Codex", "codex"),
    ("hermes", "Hermes", "hermes"),
    ("opencode", "OpenCode", "opencode"),
    ("gemini", "Gemini CLI", "gemini"),
)


def agent_name(command: str) -> str:
    """'hermes --skills evid' -> 'hermes', '/usr/bin/fish' -> 'fish', 'env X=1 codex' -> 'codex'."""
    words = [
        w
        for w in str(command).split()
        if "=" not in w and w not in ("env", "exec", "npx", "uvx")
    ]
    return Path(words[0]).name if words else (str(command).strip() or "shell")


def available(command: str, which=None) -> bool:
    """Whether a command (flags and all) can be run: its first word resolves."""
    first = (str(command).split() or [""])[0]
    if not first or "=" in first:
        return False
    if "/" in first:
        return Path(first).expanduser().exists()
    return bool((which or shutil.which)(first))


def _config_home() -> Path:
    return Path(
        os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    ).expanduser()


def opencode_profiles(folder: Path | None = None) -> list[dict]:
    """The pairings saved by ``ocprofile save``: {name, active}, the active one first."""
    folder = Path(folder or _config_home() / "opencode" / "profiles")
    try:
        active = (folder / "active").read_text("utf-8").strip()
    except OSError:
        active = ""
    try:
        names = sorted(p.stem for p in folder.glob("*.json") if p.is_file())
    except OSError:
        return []
    if active in names:
        names.remove(active)
        names.insert(0, active)
    return [{"name": n, "active": n == active} for n in names]


def harnesses(
    default: str = "", *, profiles_dir: Path | None = None, which=None
) -> list[dict]:
    """The harnesses to offer, the default one first.

    Each entry is ``{id, label, command, installed, kind}`` and exactly one (when
    any is installed) carries ``default: True``. ``kind`` is ``agent`` for a
    catalog CLI, ``profile`` for a saved OpenCode pairing, and ``configured``
    for an ``--agent`` command the catalog does not know.
    """
    which = which or shutil.which
    entries: list[dict] = []

    def add(eid: str, label: str, command: str, kind: str) -> None:
        cmd = command.strip()
        if not cmd or any(e["command"] == cmd for e in entries):
            return
        entries.append(
            {
                "id": eid,
                "label": label,
                "command": cmd,
                "installed": available(cmd, which),
                "kind": kind,
            }
        )

    for hid, label, cmd in CATALOG:
        add(hid, label, cmd, "agent")
        if hid == "opencode" and which("opencode") and which("ocprofile"):
            for p in opencode_profiles(profiles_dir):
                add(
                    f"ocprofile:{p['name']}",
                    f"OpenCode · {p['name']}" + (" (active)" if p["active"] else ""),
                    f"ocprofile launch {p['name']}",
                    "profile",
                )

    configured = str(default or "").strip()
    if configured:
        name = agent_name(configured)
        match = next((e for e in entries if e["command"] == configured), None)
        if match is None:  # same CLI, extra flags: keep the catalog row, add the flags
            match = next(
                (
                    e
                    for e in entries
                    if e["kind"] != "profile" and agent_name(e["command"]) == name
                ),
                None,
            )
        if match is None:
            match = {
                "id": "configured",
                "label": name,
                "command": configured,
                "installed": True,
                "kind": "configured",
            }
            entries.insert(0, match)
        else:
            entries.remove(match)
            entries.insert(0, match)
            match["command"] = configured
            match["installed"] = True
        match["default"] = True
    else:
        first = next((e for e in entries if e["installed"]), None)
        if first is not None:
            entries.remove(first)
            entries.insert(0, first)
            first["default"] = True
    return entries
