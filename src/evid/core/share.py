"""A gzipped catalog of one set's public documents.

The file carries urls, tags, labels, and two content hashes. It does not
carry the PDF, the extracted text, passes, or the vector index. A document
whose url is not http or https is omitted, so a file that was only ever on
this machine stays here. Credentials in a url are removed before it is written.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from evid.services.doc_tags import parse_tags_field
from evid.utils.yaml_io import load_yaml

SCHEMA = 1
KIND = "evid-share"
_SPAN = ("start", "end", "page", "text", "prefix", "suffix")


def share_url(url: str) -> str:
    """The http(s) address to publish, or '' when *url* is not a public address.

    Userinfo (``user:password@``) is stripped so a credential does not leave
    with the catalog.
    """
    raw = (url or "").strip()
    try:
        parts = urlparse(raw)
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    netloc = parts.netloc.rsplit("@", 1)[-1]
    if not netloc or netloc.startswith(":"):
        return ""
    return urlunparse(parts._replace(scheme=parts.scheme.lower(), netloc=netloc))


def build_share(set_path: Path, slug: str) -> tuple[dict, int]:
    """``(catalog, dropped)``. *dropped* is documents left out for want of a public url."""
    docs_root = Path(set_path) / "docs"
    docs: list[dict] = []
    dropped = 0
    if docs_root.is_dir():
        for doc_dir in sorted(p for p in docs_root.iterdir() if p.is_dir()):
            info_path = doc_dir / "info.yml"
            if not info_path.is_file():
                continue
            info = _read_yaml(info_path)
            url = share_url(str(info.get("url") or ""))
            if not url:
                dropped += 1
                continue
            docs.append(_doc(doc_dir, info, url))
    docs.sort(key=lambda d: d["uuid"])
    catalog = {
        "schema": SCHEMA,
        "kind": KIND,
        "set": slug,
        "name": _set_name(set_path, slug),
        "exported": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "docs": docs,
    }
    return catalog, dropped


def write_share(set_path: Path, slug: str, dest: Path) -> tuple[int, int]:
    """Write the catalog to *dest* (gzipped JSON). Returns ``(kept, dropped)``."""
    catalog, dropped = build_share(set_path, slug)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(catalog, ensure_ascii=False, indent=1) + "\n").encode()
    with gzip.GzipFile(filename="", mode="wb", fileobj=dest.open("wb"), mtime=0) as gz:
        gz.write(payload)
    return len(catalog["docs"]), dropped


def _set_name(set_path: Path, slug: str) -> str:
    data = _read_yaml(Path(set_path) / "set.yml")
    name = data.get("name")
    return str(name) if name else slug


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if str(x).strip())
    return "" if value is None else str(value).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_path(doc_dir: Path, info: dict) -> Path | None:
    original = doc_dir / "original.pdf"
    if original.is_file():
        return original
    name = info.get("original_name") or info.get("original_filename") or ""
    if not name:
        return None
    candidate = (doc_dir / str(name)).resolve()
    try:
        candidate.relative_to(doc_dir.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _text_sha256(doc_dir: Path) -> str:
    recorded = _read_json(doc_dir / "label" / "pages.json").get("sha256")
    if isinstance(recorded, str) and recorded:
        return recorded
    text = doc_dir / "label" / "text.txt"
    if text.is_file():
        return hashlib.sha256(text.read_bytes()).hexdigest()
    return ""


def _notes(rec: dict) -> list[dict]:
    out = []
    for note in rec.get("notes") or []:
        if isinstance(note, dict):
            out.append(
                {
                    "at": note.get("at") or "",
                    "by": note.get("by") or "",
                    "text": note.get("text") or "",
                }
            )
    return out


def _span(rec: dict, *, with_key: bool) -> dict:
    item = {key: rec[key] for key in _SPAN if key in rec}
    if with_key and rec.get("key"):
        item["key"] = rec["key"]
    if rec.get("id"):
        item["id"] = rec["id"]
    for key in ("created", "by"):
        if rec.get(key):
            item[key] = rec[key]
    if rec.get("lost"):
        item["lost"] = True
    item["notes"] = _notes(rec)
    return item


def _whole(rec: dict) -> dict:
    item: dict = {"id": rec.get("id") or "", "kind": rec.get("kind") or ""}
    if item["kind"] == "label" and rec.get("key"):
        item["key"] = rec["key"]
    for key in ("created", "by"):
        if rec.get(key):
            item[key] = rec[key]
    item["notes"] = _notes(rec)
    return item


def _listed(data: dict, name: str) -> list[dict]:
    raw = data.get(name) or []
    return (
        [rec for rec in raw if isinstance(rec, dict)] if isinstance(raw, list) else []
    )


def _doc(doc_dir: Path, info: dict, url: str) -> dict:
    labels = _read_json(doc_dir / "label" / "labels.json")
    tags = info.get("tags")
    if isinstance(tags, list):
        tags = ", ".join(str(t) for t in tags)
    item = {
        "uuid": str(info.get("uuid") or doc_dir.name),
        "title": _text(info.get("title")),
        "label": _text(info.get("label") or info.get("title")),
        "authors": _text(info.get("authors") or info.get("author")),
        "dates": _text(info.get("dates")),
        "tags": parse_tags_field(str(tags or "")),
        "url": url,
        "document": [_whole(rec) for rec in _listed(labels, "document")],
        "labels": [_span(rec, with_key=True) for rec in _listed(labels, "labels")],
        "annotations": [
            _span(rec, with_key=False) for rec in _listed(labels, "annotations")
        ],
    }
    source = _text(info.get("source_name"))
    if source:
        item["source_name"] = source
    pdf = _pdf_path(doc_dir, info)
    if pdf is not None:
        item["pdf_sha256"] = _sha256(pdf)
    text_sha = _text_sha256(doc_dir)
    if text_sha:
        item["text_sha256"] = text_sha
    return item
