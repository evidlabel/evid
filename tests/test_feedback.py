"""Requests to the agent (evid.core.feedback, `evid fb`, the GUI routes, MCP)."""

from __future__ import annotations

import json

import pytest
import yaml

import evid.cli.callbacks as cb
from evid.core import feedback
from evid.services.set_manager import SetManager


@pytest.fixture
def setdir(tmp_path, monkeypatch):
    sm = SetManager(tmp_path)
    s = sm.create_set("Case")
    d = s.path / "docs" / "u1"
    d.mkdir(parents=True)
    (d / "info.yml").write_text(
        yaml.safe_dump({"uuid": "u1", "title": "Ruling", "time_added": "2024-01-01"})
    )
    (d / "original.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(cb, "DIRECTORY", tmp_path)
    return s.path


def test_add_update_delete(setdir):
    a = feedback.add(setdir, "u1", "Check the date.\nAgainst the letterhead.")
    b = feedback.add(setdir, "u1", "Is this signed?", "original.pdf")
    assert (
        (a["id"], b["id"]) == (1, 2)
        and b["path"] == "original.pdf"
        and a["status"] == "open"
    )
    feedback.update(
        setdir, 1, reply="Date is 2024-06-03 per the letterhead.", status="done"
    )
    items = feedback.read(setdir)
    assert items[0]["status"] == "done" and items[0]["reply"].startswith("Date")
    assert feedback.open_counts(items) == {"u1": 1}
    assert (
        "|-" in (setdir / feedback.FEEDBACK_FILE).read_text()
    )  # multi-line text stays readable
    feedback.delete(setdir, 2)
    assert [x["id"] for x in feedback.read(setdir)] == [1]
    assert (
        feedback.add(setdir, "u1", "next")["id"] == 2
    )  # ids keep counting from the highest
    with pytest.raises(KeyError):
        feedback.update(setdir, 99, status="done")
    with pytest.raises(ValueError, match="status"):
        feedback.update(setdir, 1, status="maybe")
    with pytest.raises(ValueError, match="empty"):
        feedback.add(setdir, "u1", "  ")


def test_cli_agent_flow(setdir, monkeypatch, capsys):
    monkeypatch.setenv("EVID_SET", "case")  # inside the set's Agent pane
    cb.fb_add_callback(text="Label the findings on p. 4", uuid="u1")
    assert capsys.readouterr().out.strip() == "#1"
    cb.fb_ls_callback()
    out = capsys.readouterr().out
    assert "#1  open  Ruling (u1)" in out and "Label the findings" in out
    cb.fb_reply_callback(id=1, text="Labelled three findings.", done=True)
    capsys.readouterr()
    cb.fb_ls_callback()
    assert "No open requests." in capsys.readouterr().out
    cb.fb_ls_callback(all=True, format="json")
    (item,) = json.loads(capsys.readouterr().out)
    assert (
        item["reply"] == "Labelled three findings."
        and item["status"] == "done"
        and item["title"] == "Ruling"
    )
    cb.fb_reopen_callback(id=1)
    cb.fb_rm_callback(id=1)
    assert feedback.read(setdir) == []
    with pytest.raises(SystemExit):
        cb.fb_reply_callback(id=7, text="x")
    with pytest.raises(SystemExit, match="No file"):
        cb.fb_add_callback(text="x", uuid="u1", path="nope.pdf")


def test_mcp_lists_open_requests(setdir):
    import asyncio

    from evid.mcpserver import build_server

    feedback.add(setdir, "u1", "open one")
    feedback.update(setdir, feedback.add(setdir, "u1", "done one")["id"], status="done")
    m = build_server(setdir.parent.parent, "case")
    items = json.loads(asyncio.run(m.call_tool("feedback", {}))[0][0].text)
    assert [x["text"] for x in items] == ["open one"]
    assert (
        len(json.loads(asyncio.run(m.call_tool("feedback", {"all": True}))[0][0].text))
        == 2
    )
