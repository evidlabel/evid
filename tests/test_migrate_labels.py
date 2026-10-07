"""evid set migrate-labels: Typst labels and machine quotes become label/ spans."""

from __future__ import annotations

import json
import subprocess

import pymupdf
import yaml

from evid.core.labels import read
from evid.services.migrate_labels import (
    _extend_gitignore,
    migrate_set,
    parse_label_json,
    parse_typst_labs,
)

TEXT = (
    "Hello evidence world. The municipality did not reply. Cost is # 5 and file_name."
)


def _pdf(path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _set(tmp_path):
    root = tmp_path / "data"
    doc = root / "sets" / "demo" / "docs" / "abcd1234"
    doc.mkdir(parents=True)
    (doc / "info.yml").write_text(
        yaml.safe_dump(
            {"uuid": "abcd1234", "title": "A ruling", "original_name": "original.pdf"}
        ),
        encoding="utf-8",
    )
    (doc / "evidmgr_meta.yml").write_text(
        yaml.safe_dump({"notes": "keep me", "indexed": True, "source_type": "other"}),
        encoding="utf-8",
    )
    _pdf(doc / "original.pdf", TEXT)
    (doc / "label.typ").write_text(
        '#lab("hello", "Hello evidence world.", "")\n'
        '#lab("municipality", "The municipality did not reply.", "why it matters")\n'
        '#lab("hash", "Cost is \\# 5 and file\\_name.", "")\n'
        '#lab("missing", "not in this document zzz", "")\n'
        "# a bare # in the body used to stop typst query\n",
        encoding="utf-8",
    )
    (doc / "text.txt").write_text(TEXT, encoding="utf-8")
    (doc / "machine.hayagriva").write_text(
        "abcd:q1:\n  type: article\n  title: Hello evidence world.\n"
        '  serial-number: "chars 0-21"\n'
        "abcd:q2:\n  type: article\n  title: no such machine quote zzz\n",
        encoding="utf-8",
    )
    (doc / "machine").mkdir()
    (doc / "machine" / "2026-01-01T00-00-00Z_ab12.json").write_text(
        json.dumps(
            {
                "id": "2026-01-01T00-00-00Z_ab12",
                "timestamp": "2026-01-01T00:00:00Z",
                "schema": 1,
                "model": "m",
                "evid_version": "0.6.1",
                "job": "find dates",
                "quotes": [],
                "results": [
                    {
                        "candidate": "Hello evidence world.",
                        "matched": True,
                        "score": 1,
                        "key": "abcd:q1",
                        "page": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (doc / "machine" / "from-candidates.json").write_text(
        json.dumps({"job": "seed", "quotes": [{"candidate": "Hello evidence world."}]}),
        encoding="utf-8",
    )
    return root, doc


def test_parse_typst_labs_unescapes_and_keeps_a_broken_body():
    text = '#lab("k", "cost is \\# 5 and file\\_name", "a note")\n# bare #\n#lab("m", "line\\nnext", "")'
    labs = parse_typst_labs(text)
    assert labs[0] == {
        "key": "k",
        "text": "cost is # 5 and file_name",
        "note": "a note",
    }
    assert labs[1]["key"] == "m"
    assert labs[1]["text"] == "line\nnext"
    # a call that never closes is skipped; the next call is still read
    broken = '#lab("nope", "unterminated)\n#lab("ok", "kept", "")'
    assert [row["key"] for row in parse_typst_labs(broken)] == ["ok"]


def test_parse_label_json_query_shape(tmp_path):
    path = tmp_path / "label.json"
    path.write_text(
        json.dumps([{"value": {"key": "k", "text": "the words", "note": "why"}}]),
        encoding="utf-8",
    )
    assert parse_label_json(path) == [{"key": "k", "text": "the words", "note": "why"}]
    path.write_text("", encoding="utf-8")
    assert parse_label_json(path) == []


def test_migrate_places_spans_archives_old_files_and_is_idempotent(tmp_path):
    root, doc = _set(tmp_path)
    report = migrate_set(root, "demo")
    assert report.docs[0].error == ""
    assert report.docs[0].placed >= 3
    assert report.docs[0].unplaced == 2  # missing label and q2
    labels = {r["key"]: r for r in read(doc)["labels"]}
    assert labels["hello"]["text"] == "Hello evidence world."
    assert labels["hello"]["by"] == "migration"
    assert (
        text_of(doc)[labels["hello"]["start"] : labels["hello"]["end"]]
        == labels["hello"]["text"]
    )
    assert labels["hash"]["text"] == "Cost is # 5 and file_name."
    assert labels["municipality"]["notes"][0]["text"] == "why it matters"
    assert labels["municipality"]["notes"][0]["by"] == "migration"
    assert "missing" not in labels
    lost = json.loads((doc / "label" / "migration.json").read_text())["unplaced"]
    assert {r["key"] for r in lost} == {"missing", "q2"}
    passes = list((doc / "pass").glob("*.json"))
    assert len(passes) == 1
    found = json.loads(passes[0].read_text())["found"]
    assert found[0]["key"] == "q1"
    assert found[0]["text"] == "Hello evidence world."
    assert (doc / "legacy" / "label.typ").is_file()
    assert (doc / "legacy" / "machine" / "from-candidates.json").is_file()
    assert not (doc / "label.typ").exists()
    assert not (doc / "machine").exists()
    meta = yaml.safe_load((doc / "evid_meta.yml").read_text())
    assert meta["indexed"] is False and meta["notes"] == "keep me"
    assert not (doc / "evidmgr_meta.yml").exists()
    again = migrate_set(root, "demo")
    assert again.docs[0].skipped == "no old labels"
    assert len(read(doc)["labels"]) == len(labels)


def test_dry_run_writes_nothing(tmp_path):
    root, doc = _set(tmp_path)
    before = sorted(p.relative_to(doc) for p in doc.rglob("*") if p.is_file())
    report = migrate_set(root, "demo", dry_run=True)
    after = sorted(p.relative_to(doc) for p in doc.rglob("*") if p.is_file())
    assert before == after
    assert report.docs[0].placed >= 3 and report.commit is None
    assert not (doc / "label").exists()


def test_existing_label_is_kept(tmp_path):
    root, doc = _set(tmp_path)
    from evid.core.labels import _write_text, add_label, span_at

    _write_text(doc, TEXT, [[0, 1]])
    add_label(doc, span_at(doc, 0, 21), "hello", by="you")
    report = migrate_set(root, "demo")
    hello = next(r for r in read(doc)["labels"] if r["key"] == "hello")
    assert hello["by"] == "you"
    assert report.docs[0].already == 1
    assert any(r["key"] == "municipality" for r in read(doc)["labels"])


def test_empty_typ_without_a_pdf_is_archived(tmp_path):
    root = tmp_path / "data"
    doc = root / "sets" / "demo" / "docs" / "empty0001"
    doc.mkdir(parents=True)
    (doc / "info.yml").write_text("uuid: empty0001\ntitle: Empty\n", encoding="utf-8")
    (doc / "label.typ").write_text("= Title\n\nno labels here\n", encoding="utf-8")
    report = migrate_set(root, "demo")
    assert report.docs[0].error == ""
    assert report.docs[0].placed == 0
    assert (doc / "legacy" / "label.typ").is_file()
    assert not (doc / "label.typ").exists()


def _unlabelled(root, uuid="plain0001"):
    doc = root / "sets" / "demo" / "docs" / uuid
    doc.mkdir(parents=True)
    (doc / "info.yml").write_text(
        f"uuid: {uuid}\ntitle: Plain\noriginal_name: original.pdf\n", encoding="utf-8"
    )
    _pdf(doc / "original.pdf", TEXT)
    return doc


def test_unlabelled_doc_gets_its_text(tmp_path):
    # It used to be archived without label/text.txt, invisible to search.
    root = tmp_path / "data"
    doc = _unlabelled(root)
    (doc / "label.typ").write_text("= Title\n\nno labels here\n", encoding="utf-8")
    (doc / "text.txt").write_text(TEXT, encoding="utf-8")
    report = migrate_set(root, "demo")
    assert report.docs[0].text and report.docs[0].error == ""
    assert "Hello evidence world." in (doc / "label" / "text.txt").read_text("utf-8")
    assert (doc / "legacy" / "text.txt").is_file()


def test_rerun_backfills_text_of_an_archived_doc(tmp_path):
    root = tmp_path / "data"
    doc = _unlabelled(root)
    (doc / "legacy").mkdir()
    (doc / "legacy" / "label.typ").write_text("= Title\n", encoding="utf-8")
    assert migrate_set(root, "demo", dry_run=True).docs[0].text
    assert not (doc / "label").exists()
    report = migrate_set(root, "demo")
    assert report.docs[0].text and not report.docs[0].skipped
    assert (doc / "label" / "text.txt").is_file()
    again = migrate_set(root, "demo")
    assert again.docs[0].skipped == "no old labels" and not again.docs[0].text


def test_commit_does_not_take_other_dirty_files(tmp_path):
    root, doc = _set(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root / "sets" / "demo", check=True)
    subprocess.run(["git", "add", "-A"], cwd=root / "sets" / "demo", check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "base"], cwd=root / "sets" / "demo", check=True
    )
    info = doc / "info.yml"
    info.write_text(info.read_text(encoding="utf-8") + "\n# dirty\n", encoding="utf-8")
    report = migrate_set(root, "demo")
    assert report.commit
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=root / "sets" / "demo",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "info.yml" not in show
    assert "label/labels.json" in show
    assert "label/text.txt" in show
    assert "legacy/label.typ" in show
    assert "legacy/machine.hayagriva" in show
    assert "legacy/text.txt" not in show
    assert (doc / "legacy" / "text.txt").is_file()
    ignore = (root / "sets" / "demo" / ".gitignore").read_text(encoding="utf-8")
    assert "**/legacy/text.txt" in ignore
    assert "!**/label/text.txt" in ignore
    for rel in (
        "docs/abcd1234/label.typ",
        "docs/abcd1234/text.txt",
        "docs/abcd1234/legacy/text.txt",
    ):
        still = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{rel}"],
            cwd=root / "sets" / "demo",
            capture_output=True,
        )
        assert still.returncode != 0, rel
    status = subprocess.run(
        ["git", "status", "--short", "--", "docs/abcd1234/info.yml"],
        cwd=root / "sets" / "demo",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "info.yml" in status


_ALLOWLIST = """/*
!/.gitignore
!/docs
/docs/**
!/docs/*/
!/docs/*/info.yml
!/docs/*/label.typ
!/docs/*/evid_meta.yml
!/docs/*/evidmgr_meta.yml
"""


def test_commit_on_an_allowlist_gitignore(tmp_path):
    """A set that tracks only label.typ still commits the new label trees."""
    root, doc = _set(tmp_path)
    repo = root / "sets" / "demo"
    (repo / ".gitignore").write_text(_ALLOWLIST, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    info = doc / "info.yml"
    info.write_text(info.read_text(encoding="utf-8") + "\n# dirty\n", encoding="utf-8")
    report = migrate_set(root, "demo")
    assert report.commit
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "label/labels.json" in show
    assert "label/text.txt" in show
    assert "legacy/label.typ" in show
    assert "legacy/text.txt" not in show
    assert "info.yml" not in show
    gone = subprocess.run(
        ["git", "cat-file", "-e", "HEAD:docs/abcd1234/label.typ"],
        cwd=repo,
        capture_output=True,
    )
    assert gone.returncode != 0
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "docs/abcd1234/label/text.txt"],
        cwd=repo,
    )
    assert ignored.returncode != 0


def test_gitignore_rewrites_a_pattern_that_misses_nested_legacy(tmp_path):
    root = tmp_path / "set"
    root.mkdir()
    path = root / ".gitignore"
    path.write_text(
        "vecdb/\nlegacy/**/label.json\nlegacy/**/label.bib\n"
        "legacy/**/label_table.bib\nlegacy/**/text.txt\n",
        encoding="utf-8",
    )
    _extend_gitignore(root)
    text = path.read_text(encoding="utf-8")
    assert "**/legacy/label.json" in text
    assert "legacy/**/" not in text
    assert "!/docs/*/label/**" in text
    again = text
    _extend_gitignore(root)
    assert path.read_text(encoding="utf-8") == again


_DENYLIST = """# Cached PDF text extraction — re-extracted from the PDF on demand.
text.txt
# typst query outputs — regenerated from label.typ by `evid set gather`.
label.json
label.bib
label_table.bib
"""


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )


def _init(repo):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)


def test_denylist_still_commits_canonical_text(tmp_path):
    """lit and lokk ignore every text.txt. label/text.txt still has to be committed."""
    root, doc = _set(tmp_path)
    repo = root / "sets" / "demo"
    (repo / ".gitignore").write_text(_DENYLIST, encoding="utf-8")
    _init(repo)
    report = migrate_set(root, "demo")
    assert report.commit
    show = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout
    assert "label/text.txt" in show
    assert "legacy/text.txt" not in show
    assert (doc / "legacy" / "text.txt").is_file()
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "docs/abcd1234/label/text.txt"], cwd=repo
    )
    assert ignored.returncode != 0


def test_rerun_records_a_deletion_the_first_commit_missed(tmp_path):
    root, doc = _set(tmp_path)
    repo = root / "sets" / "demo"
    _init(repo)
    legacy = doc / "legacy"
    legacy.mkdir()
    for name in ("label.typ", "text.txt", "machine.hayagriva"):
        (doc / name).rename(legacy / name)
    (doc / "machine").rename(legacy / "machine")
    (doc / "label").mkdir()
    (doc / "label" / "labels.json").write_text(
        '{"schema": 1, "labels": []}\n', encoding="utf-8"
    )
    (doc / "label" / "text.txt").write_text(TEXT, encoding="utf-8")
    report = migrate_set(root, "demo")
    assert report.docs[0].skipped == "no old labels"
    assert report.commit
    message = _git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert message == "record removal of archived label files"
    show = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout
    assert "label/labels.json" in show
    assert "docs/abcd1234/info.yml" not in show
    gone = subprocess.run(
        ["git", "cat-file", "-e", "HEAD:docs/abcd1234/label.typ"],
        cwd=repo,
        capture_output=True,
    )
    assert gone.returncode != 0
    again = migrate_set(root, "demo")
    assert again.commit is None
    assert again.commit_error == ""


def test_a_removed_document_stays_in_head(tmp_path):
    root, _doc = _set(tmp_path)
    repo = root / "sets" / "demo"
    other = repo / "docs" / "ffff9999"
    other.mkdir()
    (other / "info.yml").write_text("uuid: ffff9999\ntitle: Gone\n", encoding="utf-8")
    (other / "label.typ").write_text('#lab("x", "not here", "")\n', encoding="utf-8")
    _init(repo)
    subprocess.run(["rm", "-rf", str(other)], check=True)
    report = migrate_set(root, "demo")
    assert report.commit
    show = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout
    assert "ffff9999" not in show
    kept = subprocess.run(
        ["git", "cat-file", "-e", "HEAD:docs/ffff9999/label.typ"],
        cwd=repo,
        capture_output=True,
    )
    assert kept.returncode == 0


def text_of(doc) -> str:
    return (doc / "label" / "text.txt").read_text(encoding="utf-8")
