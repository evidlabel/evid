"""Git history of a document (evid.services.doc_history)."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import yaml

from evid.services.doc_history import doc_history, lab_keys

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "Agent",
            "GIT_AUTHOR_EMAIL": "a@x",
            "GIT_COMMITTER_NAME": "Agent",
            "GIT_COMMITTER_EMAIL": "a@x",
            "HOME": str(cwd),
            "PATH": "/usr/bin:/bin",
        },
    )


def test_lab_keys():
    assert lab_keys('x #lab("a", "t", "") y #lab( "b\\"q", "t", "")') == ["a", 'b\\"q']


def test_not_tracked(tmp_path):
    assert doc_history(tmp_path) == {"tracked": False, "entries": []}


def test_history_summarises_commits(tmp_path):
    root = tmp_path / "set"
    d = root / "docs" / "u1"
    d.mkdir(parents=True)
    _git(root, "init", "-q")
    (d / "info.yml").write_text(
        yaml.safe_dump({"uuid": "u1", "title": "Old", "tags": ""})
    )
    (d / "original.pdf").write_bytes(b"%PDF")
    (d / "label.typ").write_text("text\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "add u1")
    (d / "info.yml").write_text(
        yaml.safe_dump({"uuid": "u1", "title": "Cleaned", "tags": "x"})
    )
    (d / "label.typ").write_text('text #lab("k1", "q", "")\n')
    _git(root, "commit", "-qam", "tidy titles, label k1")
    (d / "machine").mkdir()
    (d / "machine" / "p1.json").write_text(
        json.dumps(
            {
                "id": "p1",
                "job": "find dates",
                "results": [{"matched": True}, {"matched": False}],
            }
        )
    )
    (d / "annotations.yml").write_text(yaml.safe_dump({"original.pdf": "Signed."}))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "quote pass")
    (d / "label.typ").write_text('text #lab("k2", "q", "")\n')  # uncommitted: k1 -> k2

    h = doc_history(d)
    assert h["tracked"] is True
    wip, c3, c2, c1 = h["entries"]
    assert wip["uncommitted"] and wip["items"] == [
        {"kind": "labels", "file": "label.typ", "added": ["k2"], "removed": ["k1"]}
    ]
    assert c3["subject"] == "quote pass" and c3["author"] == "Agent"
    kinds = {i["kind"]: i for i in c3["items"]}
    assert kinds["pass"]["job"] == "find dates" and (
        kinds["pass"]["matched"],
        kinds["pass"]["tried"],
    ) == (1, 2)
    assert kinds["notes"]["paths"] == ["original.pdf"]
    by = {i["kind"]: i for i in c2["items"]}
    assert by["details"]["fields"] == ["tags", "title"] and by["labels"]["added"] == [
        "k1"
    ]
    assert [i["kind"] for i in c1["items"]] == [
        "added"
    ]  # the new doc, not a list of its files


def test_binary_files_are_not_read(tmp_path):
    root = tmp_path / "set"
    d = root / "docs" / "u1"
    d.mkdir(parents=True)
    _git(root, "init", "-q")
    (d / "info.yml").write_text(yaml.safe_dump({"uuid": "u1", "title": "T"}))
    (d / "original.pdf").write_bytes(bytes(range(256)) * 4)  # not UTF-8
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "add")
    (d / "original.pdf").write_bytes(b"\xda\xff" * 100)
    _git(root, "commit", "-qam", "replace the scan")
    h = doc_history(d)
    assert h["entries"][0]["items"] == [
        {"kind": "files", "what": "edited", "files": ["original.pdf"]}
    ]
