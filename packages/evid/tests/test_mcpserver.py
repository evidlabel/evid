"""Tests for the evid MCP server: single-dataset scoping + tool wiring."""

from __future__ import annotations

import asyncio
import json

import pytest
import yaml
from evid.mcpserver import build_server
from evid.services.set_manager import SetManager


def _text(call_result):
    """FastMCP call_tool returns (content_blocks, structured)."""
    return call_result[0][0].text


def _seed(tmp_path):
    sm = SetManager(tmp_path)
    s = sm.create_set("My Case")
    doc_dir = s.path / "docs" / "u1"
    doc_dir.mkdir(parents=True)
    with (doc_dir / "info.yml").open("w", encoding="utf-8") as f:
        yaml.safe_dump({"uuid": "u1", "title": "Judgment 2024", "tags": "priority"}, f)
    (doc_dir / "label.typ").write_text(
        "= Judgment 2024\n\n#mset(values: (opage: 1))\n== Page 1\n"
        "The defendant was responsible for the safety inspections.\n",
        encoding="utf-8",
    )
    return sm


def test_tools_registered_no_list_sets(tmp_path):
    _seed(tmp_path)
    m = build_server(tmp_path, "my-case")
    names = {t.name for t in asyncio.run(m.list_tools())}
    # Scoped server: no list_sets discovery tool.
    assert names == {
        "search_vec",
        "search_text",
        "search_meta",
        "list_docs",
        "doc_quotes",
    }


def test_tools_take_no_dataset_arg(tmp_path):
    _seed(tmp_path)
    m = build_server(tmp_path, "my-case")
    tools = {t.name: t for t in asyncio.run(m.list_tools())}
    for name in ("search_vec", "search_text", "search_meta", "list_docs"):
        props = tools[name].inputSchema.get("properties", {})
        assert "dataset" not in props, f"{name} must not expose a dataset param"


def test_list_docs_scoped(tmp_path):
    _seed(tmp_path)
    m = build_server(tmp_path, "my-case")
    docs = json.loads(_text(asyncio.run(m.call_tool("list_docs", {}))))
    assert docs[0]["uuid"] == "u1"


def test_search_meta_scoped(tmp_path):
    _seed(tmp_path)
    m = build_server(tmp_path, "my-case")
    docs = json.loads(
        _text(asyncio.run(m.call_tool("search_meta", {"pattern": "Judg"})))
    )
    assert docs[0]["label"] == "Judgment 2024"


def test_search_text_scoped(tmp_path):
    _seed(tmp_path)
    m = build_server(tmp_path, "my-case")
    hits = json.loads(
        _text(
            asyncio.run(
                m.call_tool(
                    "search_text", {"query": "responsible for the safety inspections"}
                )
            )
        )
    )
    assert hits
    assert hits[0]["uuid"] == "u1"


def test_resolve_by_display_name(tmp_path):
    _seed(tmp_path)
    # bound by display name, not just slug
    m = build_server(tmp_path, "My Case")
    docs = json.loads(_text(asyncio.run(m.call_tool("list_docs", {}))))
    assert docs[0]["uuid"] == "u1"


def test_unknown_dataset_errors_at_startup(tmp_path):
    _seed(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        build_server(tmp_path, "nope")
