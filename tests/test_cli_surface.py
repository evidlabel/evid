"""Headless tests of the CLI surface as an agent (or a human) discovers it.

These build the real treeparse tree and assert the properties that keep evid
usable as an agent-callable tool:

- the whole tree binds without name/type mismatches (treeparse's ``_validate``
  runs on ``build_parser`` — this is the guard that would have caught flag-vs-
  callback type drift that makes a command unparseable at runtime),
- uniform shallow depth (``evid <group> <verb>``),
- no duplicate-behavior aliases ("same as" flags),
- the ``export`` group owns every export verb, so ``evid export --help``
  surfaces them all,
- ``doc add`` metadata vocabulary and the removed ``-a`` alias,
- the ``-j`` JSON schema dumps cleanly and reflects the tree,
- ``doc quote`` enforces exactly-one seed source.

No terminal, no live directory, no network: everything runs against the
in-memory tree or a tmpdir.
"""

from __future__ import annotations

import json
import sys

import pytest

from evid.cli import main as m
from evid.cli import callbacks


# ── helpers ──────────────────────────────────────────────────────────────────

def _all_commands(node=None, path=()):
    """Yield (path_tokens, command_obj) for every leaf command in the tree."""
    node = node or m.app
    p = (*path, getattr(node, "name", None) or "evid")
    for c in getattr(node, "commands", []):
        yield (*p, c.name), c
    for g in getattr(node, "subgroups", []):
        yield from _all_commands(g, p)


def _find(group: str, cmd: str):
    grp = next(g for g in m.app.subgroups if g.name == group)
    return next(c for c in grp.commands if c.name == cmd)


# ── the tree binds (regression guard for the reported failure) ───────────────

def test_full_tree_validates_bindings():
    """build_parser() runs treeparse._validate over EVERY command; a callback
    param typed against a version-drifted option (e.g. flags resolved to str)
    raises here, so `evid <anything>` stays parseable."""
    m.app.build_parser()  # raises ValueError on any binding/type mismatch


def test_every_command_has_a_registered_callback():
    for path, cmd in _all_commands():
        assert callable(cmd.callback), "{} has no callback".format(" ".join(path))


# ── uniform shallow depth ────────────────────────────────────────────────────

def test_tree_is_shallow_and_uniform():
    depths = {len(path) - 1 for path, _ in _all_commands()}  # tokens after 'evid'
    # group-backed leaves are evid <group> <verb> (depth 2); root commands are 1
    assert depths <= {1, 2}, f"leaf depths went deeper than two levels: {depths}"
    assert 2 in depths  # the common, expected shape exists


# ── no duplicate-behavior aliases ────────────────────────────────────────────

def test_no_duplicate_behaviour_aliases():
    for path, cmd in _all_commands():
        helps = [o.help for o in getattr(cmd, "options", []) if getattr(o, "help", None)]
        for h in helps:
            assert "same as" not in h.lower(), (
                "{} has a duplicate alias ('{}')".format(" ".join(path), h)
            )
        # identical help on two options is a duplicate in disguise
        seen = set()
        for o in getattr(cmd, "options", []):
            if getattr(o, "help", None):
                assert o.help not in seen, "{} repeats help: {}".format(" ".join(path), o.help)
                seen.add(o.help)


# ── export group owns every export verb ──────────────────────────────────────

def test_export_group_owns_bibtex_export_verbs():
    grp = next(g for g in m.app.subgroups if g.name == "export")
    assert {c.name for c in grp.commands} >= {"gather", "share", "merge"}
    set_group = next(g for g in m.app.subgroups if g.name == "set")
    assert not {c.name for c in set_group.commands} & {"gather", "share"}
    assert not any(g.name == "refs" for g in m.app.subgroups)


# ── doc add: metadata vocabulary, alias removed ──────────────────────────────

def test_doc_add_has_metadata_flags_and_no_alias():
    add = _find("doc", "add")
    flags = {f for o in add.options for f in o.flags}
    assert {"--title", "--authors", "--dates", "--url", "-l", "--label", "--no-index"} <= flags
    assert not (flags & {"-a", "--autolabel"}), "-a/--autolabel must not reappear"


def test_help_is_an_agent_surface(capsys):
    """--help is what an agent reads; the removed alias must not show there."""
    sys.argv = ["evid", "doc", "add", "--help"]
    with pytest.raises(SystemExit):
        m.main()
    out = capsys.readouterr().out
    assert "autolabel" not in out and "-a," not in out.replace(" ", "")
    assert "--title" in out


# ── -j JSON schema (the headline agent affordance) ───────────────────────────

def test_json_schema_dumps_and_reflects_export(capsys):
    sys.argv = ["evid", "-j"]
    with pytest.raises(SystemExit):
        m.main()
    out = capsys.readouterr().out
    schema = json.loads(out)
    subgroups = {g["name"] for g in schema.get("subgroups", [])}
    assert "export" in subgroups and "refs" not in subgroups
    export = next(g for g in schema["subgroups"] if g["name"] == "export")
    assert {c["name"] for c in export["commands"]} >= {"gather", "share", "merge"}


# ── doc quote enforces exactly one seed ──────────────────────────────────────

def test_quote_requires_exactly_one_seed(monkeypatch):
    # _resolve_dataset would prompt; stub it so we reach the guard deterministically.
    monkeypatch.setattr(callbacks, "_resolve_dataset", lambda *a, **k: "demo")
    with pytest.raises(SystemExit) as e:
        callbacks.quote_callback(dataset=None)
    assert "exactly one" in str(e.value).lower()
    with pytest.raises(SystemExit) as e:
        callbacks.quote_callback(dataset=None, from_path="a.json", from_search="q")
    assert "exactly one" in str(e.value).lower()
