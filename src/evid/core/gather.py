"""Gather a set's citable passages into one file (Hayagriva, BibTeX, Markdown, JSON).

Since evid 0.7 the passages are spans over each document's canonical text:
human labels from ``label/labels.json`` and machine quotes from ``pass/*.json``.
Every export is built from those records; Typst is only used to render (the
``.typ`` output). The Hayagriva shape is the one labquote reads:
``<uuid4>:main`` for the document, ``<uuid4>:<key>`` per passage with the
verbatim text as ``title``, ``page-range`` and ``serial-number: "chars a-b"``.
"""

import datetime
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import bibtexparser as btp
import yaml
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bwriter import BibTexWriter
from rich.console import Console
from rich.table import Table

from evid.core.hayagriva_fields import hayagriva_author, hayagriva_date
from evid.models import InfoModel

logger = logging.getLogger(__name__)

_TYPST_BIBLIO_TEMPLATE = """\
#set text(lang: "da")
#set text(font: "New Computer Modern", size: 12pt)

#bibliography("BIBNAME", title: "Referencer", style: "ieee", full: true)
"""


@dataclass
class Passage:
    key: str  # the record's key within the document: a label key, or qN
    text: str
    page: int | None
    start: int
    end: int
    note: str
    kind: str  # "label" or "machine"


@dataclass
class DocRecords:
    uuid_dir: Path
    info: InfoModel
    prefix: str
    passages: list[Passage]


def _parse_date_spec(spec: str) -> datetime.date:
    """Parse a --since/--until value into a date.

    Accepts 'YYYY-MM-DD', 'today', 'yesterday', or 'Nd' / 'N' (N days ago).
    """
    s = spec.strip().lower()
    today = datetime.date.today()
    if s == "today":
        return today
    if s == "yesterday":
        return today - datetime.timedelta(days=1)
    m = re.fullmatch(r"(\d+)d?", s)  # "7d" or "7"
    if m:
        return today - datetime.timedelta(days=int(m.group(1)))
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        sys.exit(
            f"Invalid date spec '{spec}'. Use YYYY-MM-DD, today, yesterday, or Nd."
        )


def _names_in_range(
    dataset_dir: Path,
    since: datetime.date | None,
    until: datetime.date | None,
) -> set[str]:
    """UUID dir names whose info.yml time_added is within [since, until]."""
    keep: set[str] = set()
    for uuid_dir in dataset_dir.iterdir():
        if not uuid_dir.is_dir():
            continue
        info_file = uuid_dir / "info.yml"
        if not info_file.exists():
            continue
        try:
            raw = yaml.safe_load(info_file.read_text(encoding="utf-8"))
            added_raw = InfoModel(**raw).time_added
            added = datetime.date.fromisoformat(str(added_raw)[:10])
        except Exception:
            logger.debug("Skipping %s: missing/invalid time_added", uuid_dir.name)
            continue  # no valid date -> excluded when a date filter is active
        if since and added < since:
            continue
        if until and added > until:
            continue
        keep.add(uuid_dir.name)
    return keep


def collect(
    dataset_dir: Path, keep: set[str] | None = None
) -> tuple[list[DocRecords], list[str]]:
    """Every document with a valid info.yml, with its labels and pass quotes."""
    from evid.core import labels
    from evid.core.quote_pass import found_quotes

    docs: list[DocRecords] = []
    legacy: list[str] = []
    for uuid_dir in sorted(d for d in dataset_dir.iterdir() if d.is_dir()):
        if keep is not None and uuid_dir.name not in keep:
            continue
        info_file = uuid_dir / "info.yml"
        if not info_file.exists():
            continue
        try:
            with info_file.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            info = InfoModel(**{**raw, "uuid": raw.get("uuid") or uuid_dir.name})
        except Exception as exc:
            logger.warning("Skipping %s: %s", uuid_dir.name, exc)
            continue
        if (uuid_dir / "label.typ").exists() and not (
            uuid_dir / labels.LABEL_DIR / labels.LABELS_FILE
        ).exists():
            legacy.append(uuid_dir.name)
        passages = [
            Passage(
                r["key"],
                r["text"],
                r.get("page"),
                r["start"],
                r["end"],
                labels.notes_text(r),
                "label",
            )
            for r in labels.read(uuid_dir)["labels"]
            if not r.get("lost")
        ]
        passages += [
            Passage(
                q["key"],
                q["text"],
                q.get("page"),
                q["start"],
                q["end"],
                labels.notes_text(q),
                "machine",
            )
            for q in found_quotes(uuid_dir)
            if not q.get("lost")
        ]
        passages.sort(key=lambda p: (p.start, p.key))
        docs.append(DocRecords(uuid_dir, info, info.uuid[:4], passages))
    return docs, legacy


def gather_dataset(
    directory: Path,
    dataset: str,
    output: Path,
    regen: bool = True,
    include_keys: bool = False,
    since: str | None = None,
    until: str | None = None,
) -> None:
    """Gather all labels and machine quotes of a dataset into one file.

    Output format is inferred from the file extension:
      .yaml / .yml — Hayagriva (labquote, Typst's bibliography)
      .bib         — BibTeX
      .typ         — Typst bibliography document + .bib; attempts typst compile
      .md          — Markdown report listing all passages
      .json        — JSON keyed by UUID
    """
    dataset_dir = directory / "sets" / dataset / "docs"
    if not dataset_dir.is_dir():
        sys.exit(f"Dataset docs directory '{dataset_dir}' does not exist.")

    keep: set[str] | None = None
    if since or until:
        since_d = _parse_date_spec(since) if since else None
        until_d = _parse_date_spec(until) if until else datetime.date.today()
        keep = _names_in_range(dataset_dir, since_d, until_d)
        if not keep:
            sys.exit("No documents added in the given date range.")

    docs, legacy = collect(dataset_dir, keep)
    if legacy:
        logger.warning(
            "%d document(s) still have Typst labels (label.typ) that gather no longer reads: "
            "run `evid set migrate-labels -s %s`",
            len(legacy),
            dataset,
        )
    if not any(d.passages for d in docs):
        sys.exit(f"No labels or machine quotes in dataset '{dataset}'.")

    suffix = output.suffix.lower()
    if suffix == ".bib":
        output.write_text(to_bibtex(docs), encoding="utf-8")
    elif suffix == ".typ":
        bib_file = output.with_suffix(".bib")
        bib_file.write_text(to_bibtex(docs), encoding="utf-8")
        output.write_text(
            _TYPST_BIBLIO_TEMPLATE.replace("BIBNAME", bib_file.name), encoding="utf-8"
        )
        if not _compile_with_fix(output, bib_file):
            logger.error(
                "Typst compile finished with unresolved errors. Check %s for commented-out entries.",
                bib_file,
            )
    elif suffix == ".md":
        output.write_text(
            to_markdown(docs, dataset, include_keys=include_keys), encoding="utf-8"
        )
    elif suffix == ".json":
        import json

        output.write_text(
            json.dumps(to_json(docs), indent=2, ensure_ascii=False), encoding="utf-8"
        )
    elif suffix in (".yaml", ".yml"):
        output.write_text(to_hayagriva(docs), encoding="utf-8")
    else:
        sys.exit(
            f"Unsupported output format '{suffix}'. Use .bib, .typ, .md, .json, .yaml, or .yml."
        )

    _print_gather_stats(docs, dataset, output, legacy)


# ── exporters ────────────────────────────────────────────────────────────────


def _flat(value: str) -> str:
    return " ".join(str(value).split())


def _keys(doc: DocRecords) -> list[tuple[str, Passage]]:
    """Unique citation keys ``<prefix>:<key>`` (a clash gets _2, _3 …)."""
    seen: set[str] = set()
    out = []
    for p in doc.passages:
        key, n = f"{doc.prefix}:{p.key}", 2
        while key in seen or p.key == "main":
            key, n = f"{doc.prefix}:{p.key}_{n}", n + 1
        seen.add(key)
        out.append((key, p))
    return out


def to_hayagriva(docs: list[DocRecords]) -> str:
    from evid import __version__ as evid_version

    gen = datetime.date.today().isoformat()
    chunks: list[str] = []
    taken: set[str] = set()
    for doc in docs:
        if not doc.passages:
            continue
        info = doc.info
        author, date, url = (
            hayagriva_author(info.authors),
            hayagriva_date(info.dates),
            info.url or None,
        )
        wm = (
            f"# generated-by: evid v{evid_version} · {gen}"
            + (f" · {url}" if url else "")
            + "\n"
        )
        main = {"type": "article", "title": _flat(info.title or info.label)}
        main.update(
            {k: v for k, v in (("author", author), ("date", date), ("url", url)) if v}
        )
        main_key = f"{doc.prefix}:main"
        if main_key in taken:  # two documents share a uuid prefix
            logger.warning(
                "Two documents share the key prefix %s; the second is %s",
                doc.prefix,
                doc.uuid_dir.name,
            )
        taken.add(main_key)
        chunks.append(
            wm
            + yaml.safe_dump(
                {main_key: main}, allow_unicode=True, sort_keys=False, width=1000
            )
        )
        for key, p in _keys(doc):
            item = {"type": "article", "title": p.text}
            item.update(
                {
                    k: v
                    for k, v in (("author", author), ("date", date), ("url", url))
                    if v
                }
            )
            if p.page:
                item["page-range"] = str(p.page)
            item["serial-number"] = f"chars {p.start}-{p.end}"
            item["parent"] = {
                "type": "article",
                "title": _flat(info.title or info.label),
            }
            if p.note:
                item["note"] = _flat(p.note)
            head = (
                "# verbatim, rapidfuzz-verified\n"
                if p.kind == "machine"
                else "# verbatim label\n"
            )
            chunks.append(wm + head + _dump_entry(key, item))
    return "\n".join(chunks)


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(
    str,
    lambda d, s: d.represent_scalar(
        "tag:yaml.org,2002:str", s, style="|" if "\n" in s else None
    ),
)


def _dump_entry(key: str, item: dict) -> str:
    return yaml.dump(
        {key: item}, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=1000
    )


def to_bibtex(docs: list[DocRecords]) -> str:
    db = BibDatabase()
    entries = []
    for doc in docs:
        if not doc.passages:
            continue
        info = doc.info
        base = {
            k: v
            for k, v in (
                ("author", _flat(info.authors)),
                ("date", hayagriva_date(info.dates) or ""),
                ("url", info.url),
            )
            if v
        }
        entries.append(
            {
                "ENTRYTYPE": "article",
                "ID": f"{doc.prefix}:main",
                "title": _flat(info.title or info.label),
                **base,
            }
        )
        for key, p in _keys(doc):
            e = {
                "ENTRYTYPE": "article",
                "ID": key,
                "title": _flat(p.text),
                "journal": _flat(info.title or info.label),
                **base,
            }
            if p.page:
                e["pages"] = str(p.page)
            if p.note:
                e["note"] = _flat(p.note)
            entries.append(e)
    db.entries = entries
    writer = BibTexWriter()
    writer.order_entries_by = None
    return btp.dumps(db, writer)


def to_markdown(
    docs: list[DocRecords], dataset: str, include_keys: bool = False
) -> str:
    n = sum(len(d.passages) for d in docs)
    lines = [
        f"# Label extraction: {dataset}\n",
        f"- **Date**: {datetime.date.today().isoformat()}",
        f"- **Documents**: {len(docs)}",
        f"- **Snippets**: {n}",
        "",
    ]
    for doc in docs:
        info = doc.info
        lines.append(f"## {info.title}\n")
        for label, value in (
            ("Author", info.authors),
            ("Date", info.dates),
            ("URL", info.url),
        ):
            if value:
                lines.append(f"- **{label}**: {value}")
        lines.append("")
        for key, p in _keys(doc):
            if include_keys:
                lines.append(f"  ### {key.split(':', 1)[1]}")
            prefix = f"p. {p.page}: " if p.page else ""
            lines.append(f"  - {prefix}{p.text.replace(chr(10), chr(10) + '    ')}")
            if p.note:
                lines.append(f"    *Note:* {p.note.replace(chr(10), ' / ')}")
            lines.append("")
    return "\n".join(lines)


def to_json(docs: list[DocRecords]) -> dict:
    out: dict = {}
    for doc in docs:
        info = doc.info
        out[info.uuid] = {
            "url": info.url,
            "title": info.title,
            "author": info.authors,
            "date": info.dates,
            "tags": info.tags,
            "snippets": {
                key: {
                    "pageno": str(p.page or ""),
                    "text": p.text,
                    "note": p.note,
                    "kind": p.kind,
                    "start": p.start,
                    "end": p.end,
                }
                for key, p in _keys(doc)
            },
        }
    return out


def _print_gather_stats(
    docs: list[DocRecords], dataset: str, output: Path, legacy: list[str]
) -> None:
    table = Table(title=f"gather: {dataset}", show_header=True)
    table.add_column("", style="dim")
    table.add_column("")
    table.add_row("Output", str(output))
    table.add_row("Documents", str(len(docs)))
    table.add_row("With passages", str(sum(1 for d in docs if d.passages)))
    table.add_row(
        "Labels", str(sum(1 for d in docs for p in d.passages if p.kind == "label"))
    )
    table.add_row(
        "Machine quotes",
        str(sum(1 for d in docs for p in d.passages if p.kind == "machine")),
    )
    if legacy:
        table.add_row("Not migrated (label.typ)", str(len(legacy)))
    Console().print(table)


def _compile_with_fix(typ_file: Path, bib_file: Path, max_retries: int = 30) -> bool:
    """Try typst compile; on each failure comment out the offending BibTeX entry."""
    for attempt in range(max_retries):
        result = subprocess.run(
            ["typst", "compile", str(typ_file)],
            capture_output=True,
            text=True,
            cwd=typ_file.parent,
        )
        if result.returncode == 0:
            return True
        stderr = result.stderr
        logger.debug(f"Compile attempt {attempt + 1} failed:\n{stderr}")
        key = _extract_offending_key(stderr)
        if not key:
            logger.error(
                f"Typst compile failed and no offending key could be identified.\n{stderr}"
            )
            return False
        found = _comment_out_entry(bib_file, key)
        if not found:
            logger.error(
                f"Could not locate entry '{key}' in {bib_file} to comment out.\n{stderr}"
            )
            return False
        logger.warning(
            f"Commented out problematic BibTeX entry '{key}'; retrying compile."
        )
    logger.error(f"Compile still failing after {max_retries} retries.")
    return False


def _extract_offending_key(stderr: str) -> str | None:
    """Parse Typst compile stderr to find an offending citation/label key."""
    patterns = [
        # Typst: label `<key>` does not exist
        r"label `<([^>]+)>`",
        # Typst: unknown citation key "key"
        r'unknown citation key[:\s]+"([^"]+)"',
        # Typst: unknown citation key `key`
        r"unknown citation key[:\s]+`([^`]+)`",
        # Typst bibliography parse error mentioning key
        r'bibliography.*?["\']([A-Za-z0-9_:\-]+)["\']',
        # Generic: cite key = something
        r'cite\w*[:\s=]+"?([A-Za-z0-9_:\-]+)"?',
    ]
    for pattern in patterns:
        m = re.search(pattern, stderr)
        if m:
            return m.group(1)
    return None


def _comment_out_entry(bib_file: Path, key: str) -> bool:
    """Comment out (prefix with %) all lines of a specific @entry block in the bib file."""
    text = bib_file.read_text(encoding="utf-8")

    # Match the entire @type{key, ... } block (handles nested braces via brace counting)
    header_pattern = re.compile(r"(@\w+\{" + re.escape(key) + r"\s*,)", re.IGNORECASE)
    match = header_pattern.search(text)
    if not match:
        return False

    start = match.start()
    # Walk forward counting braces to find the end of this entry
    depth = 0
    end = start
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    entry_block = text[start:end]
    commented = "\n".join(f"% {line}" for line in entry_block.splitlines())
    new_text = text[:start] + commented + text[end:]
    bib_file.write_text(new_text, encoding="utf-8")
    return True
