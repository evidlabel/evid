"""Gather all BibTeX from a dataset into a single output file."""

import logging
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import bibtexparser as btp
import yaml
from bibtexparser.bwriter import BibTexWriter
from rich.console import Console
from rich.table import Table

from evid.core.bibtex import generate_bib_from_typ
from evid.core.models import InfoModel

logger = logging.getLogger(__name__)

_TYPST_BIBLIO_TEMPLATE = """\
#set text(lang: "da")
#set text(font: "New Computer Modern", size: 12pt)

#bibliography("BIBNAME", title: "Referencer", style: "ieee", full: true)
"""


def gather_dataset(
    directory: Path,
    dataset: str,
    output: Path,
    regen: bool = True,
    include_keys: bool = False,
) -> None:
    """Gather all BibTeX from a dataset into a single output file.

    Args:
        regen: When True (default), re-run ``typst query`` on every label.typ
               before collecting.  When False, use whatever label.bib files
               already exist on disk — much faster but may be stale.
        include_keys: When True, emit ``###`` sub-headings with the user-defined
               label key name for each snippet.  Off by default to avoid
               influencing downstream LLMs with key name choices.

    Output format is inferred from the file extension:
      .bib         — combined, deduplicated BibTeX
      .typ         — Typst bibliography document + .bib; attempts typst compile
      .md          — Markdown report listing all entries
      .json        — JSON keyed by UUID
      .yaml / .yml — Hayagriva YAML bibliography (Typst-native)
    """
    dataset_dir = directory / "sets" / dataset / "docs"
    if not dataset_dir.is_dir():
        sys.exit(f"Dataset docs directory '{dataset_dir}' does not exist.")

    if regen:
        bib_texts, errors = _collect_bibs_regen(dataset_dir)
    else:
        bib_texts, errors = _collect_bibs_existing(dataset_dir)

    if errors:
        for err in errors:
            logger.warning(err)

    if not bib_texts:
        sys.exit(f"No BibTeX content collected from dataset '{dataset}'.")

    combined = "\n".join(bib_texts)
    fixed = _fix_duplicate_keys(combined)

    suffix = output.suffix.lower()
    if suffix == ".bib":
        output.write_text(fixed, encoding="utf-8")
    elif suffix == ".typ":
        bib_file = output.with_suffix(".bib")
        bib_file.write_text(fixed, encoding="utf-8")
        typ_content = _TYPST_BIBLIO_TEMPLATE.replace("BIBNAME", bib_file.name)
        output.write_text(typ_content, encoding="utf-8")
        ok = _compile_with_fix(output, bib_file)
        if not ok:
            logger.error(
                "Typst compile finished with unresolved errors. "
                "Check %s for commented-out entries.",
                bib_file,
            )
    elif suffix == ".md":
        md = _dataset_to_markdown(dataset_dir, dataset, include_keys=include_keys)
        output.write_text(md, encoding="utf-8")
    elif suffix == ".json":
        import json

        data = _dataset_to_json(dataset_dir)
        output.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    elif suffix in (".yaml", ".yml"):
        output.write_text(_bib_to_hayagriva(fixed), encoding="utf-8")
    else:
        sys.exit(
            f"Unsupported output format '{suffix}'. "
            "Use .bib, .typ, .md, .json, .yaml, or .yml."
        )

    _print_gather_stats(dataset_dir, dataset, output, errors)


def _collect_bibs_regen(dataset_dir: Path) -> tuple[list[str], list[str]]:
    """Re-run typst query on every label.typ in parallel, then collect bibs."""
    uuid_dirs = [d for d in sorted(dataset_dir.iterdir()) if d.is_dir()]
    typ_files = [d / "label.typ" for d in uuid_dirs if (d / "label.typ").exists()]

    if not typ_files:
        return [], []

    # Results keyed by typ_file so we can preserve sorted order.
    results: dict[Path, tuple[bool, str]] = {}

    stale = []
    for t in typ_files:
        bib = t.parent / "label.bib"
        if bib.exists() and bib.stat().st_mtime >= t.stat().st_mtime:
            results[t] = (True, "")
        else:
            stale.append(t)

    with ThreadPoolExecutor() as executor:
        future_to_typ = {executor.submit(generate_bib_from_typ, t): t for t in stale}
        for future in as_completed(future_to_typ):
            typ_file = future_to_typ[future]
            try:
                results[typ_file] = future.result()
            except Exception as exc:
                results[typ_file] = (False, str(exc))

    bib_texts: list[str] = []
    errors: list[str] = []
    for typ_file in typ_files:  # iterate in original sorted order
        success, msg = results[typ_file]
        if success:
            bib_file = typ_file.parent / "label.bib"
            if bib_file.exists():
                bib_texts.append(bib_file.read_text(encoding="utf-8"))
            else:
                errors.append(
                    f"label.bib missing after successful generation in {typ_file.parent}"
                )
        else:
            errors.append(msg)

    return bib_texts, errors


def _collect_bibs_existing(dataset_dir: Path) -> tuple[list[str], list[str]]:
    """Collect existing label.bib files without re-running typst."""
    bib_texts: list[str] = []
    errors: list[str] = []

    for uuid_dir in sorted(dataset_dir.iterdir()):
        if not uuid_dir.is_dir():
            continue
        bib_file = uuid_dir / "label.bib"
        if not bib_file.exists():
            logger.debug(f"Skipping {uuid_dir.name}: no label.bib")
            continue
        bib_texts.append(bib_file.read_text(encoding="utf-8"))

    return bib_texts, errors


def _fix_duplicate_keys(bib_text: str) -> str:
    """Rename duplicate BibTeX entry keys by appending _2, _3, etc."""
    db = btp.loads(bib_text)
    seen: dict[str, int] = {}
    for entry in db.entries:
        key = entry["ID"]
        if key in seen:
            seen[key] += 1
            entry["ID"] = f"{key}_{seen[key]}"
        else:
            seen[key] = 1
    writer = BibTexWriter()
    return writer.write(db)


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


def _print_gather_stats(
    dataset_dir: Path,
    dataset: str,
    output: Path,
    errors: list[str],
) -> None:
    """Print a Rich summary table after gather completes."""
    uuid_dirs = [d for d in sorted(dataset_dir.iterdir()) if d.is_dir()]
    n_docs = sum(1 for d in uuid_dirs if (d / "info.yml").exists())
    n_with_bib = sum(1 for d in uuid_dirs if (d / "label.bib").exists())
    n_snippets = 0
    for d in uuid_dirs:
        bib_file = d / "label.bib"
        if bib_file.exists():
            try:
                db = btp.loads(bib_file.read_text(encoding="utf-8"))
                n_snippets += sum(
                    1
                    for e in db.entries
                    if (e["ID"].split(":", 1)[1] if ":" in e["ID"] else e["ID"])
                    != "main"
                )
            except Exception:
                pass

    console = Console()
    table = Table(title=f"gather: {dataset}", show_header=True)
    table.add_column("", style="dim")
    table.add_column("")
    table.add_row("Output", str(output))
    table.add_row("Documents", str(n_docs))
    table.add_row("With snippets", str(n_with_bib))
    table.add_row("Snippets", str(n_snippets))
    if errors:
        table.add_row("Warnings", str(len(errors)), end_section=True)
    console.print(table)


def _dataset_to_markdown(
    dataset_dir: Path, dataset: str, include_keys: bool = False
) -> str:
    """Build a Markdown report by reading info.yml and label.bib from each UUID dir.

    Every UUID dir with a valid info.yml appears as a ``##`` section regardless
    of whether a label.bib exists.  Snippet bullets are only emitted when a
    label.bib is present.
    """
    import datetime

    uuid_dirs = sorted(d for d in dataset_dir.iterdir() if d.is_dir())

    docs: list[tuple[InfoModel, list[tuple[str, str, str]]]] = []
    for uuid_dir in uuid_dirs:
        info_file = uuid_dir / "info.yml"
        if not info_file.exists():
            logger.debug("Skipping %s: no info.yml", uuid_dir.name)
            continue
        try:
            with info_file.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            info = InfoModel(**raw)
        except Exception as exc:
            logger.warning("Skipping %s: %s", uuid_dir, exc)
            continue

        snippets: list[tuple[str, str, str]] = []  # (label, page, text)
        bib_file = uuid_dir / "label.bib"
        if bib_file.exists():
            try:
                db = btp.loads(bib_file.read_text(encoding="utf-8"))
                for entry in db.entries:
                    key = entry["ID"]
                    label = key.split(":", 1)[1] if ":" in key else key
                    if label == "main":
                        continue
                    snippets.append(
                        (label, entry.get("pages", ""), entry.get("title", ""))
                    )
            except Exception as exc:
                logger.warning(
                    "Could not parse label.bib in %s: %s", uuid_dir.name, exc
                )

        docs.append((info, snippets))

    n_snippets = sum(len(s) for _, s in docs)
    today = datetime.date.today().isoformat()

    lines = [
        f"# Label extraction: {dataset}\n",
        f"- **Date**: {today}",
        f"- **Documents**: {len(docs)}",
        f"- **Snippets**: {n_snippets}",
        "",
    ]

    for info, snippets in docs:
        lines.append(f"## {info.title}\n")
        if info.authors:
            lines.append(f"- **Author**: {info.authors}")
        if info.dates:
            lines.append(f"- **Date**: {info.dates}")
        if info.url:
            lines.append(f"- **URL**: {info.url}")
        lines.append("")

        for label, page, text in snippets:
            if include_keys:
                lines.append(f"  ### {label}")
            page_prefix = f"p. {page}: " if page else ""
            indented = text.replace("\n", "\n    ")
            lines.append(f"  - {page_prefix}{indented}")
            lines.append("")

    return "\n".join(lines)


def _dataset_to_json(dataset_dir: Path) -> dict:
    """Build a JSON-serialisable dict keyed by UUID.

    Structure::

        {
            "<uuid>": {
                "url": "...",
                "title": "...",
                "author": "...",
                "snippets": {
                    "<bib_key>": {"pageno": "5", "text": "..."},
                    ...
                }
            },
            ...
        }
    """
    result: dict = {}
    for uuid_dir in sorted(d for d in dataset_dir.iterdir() if d.is_dir()):
        info_file = uuid_dir / "info.yml"
        if not info_file.exists():
            logger.debug("Skipping %s: no info.yml", uuid_dir.name)
            continue
        try:
            with info_file.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            info = InfoModel(**raw)
        except Exception as exc:
            logger.warning("Skipping %s: %s", uuid_dir, exc)
            continue

        snippets: dict = {}
        bib_file = uuid_dir / "label.bib"
        if bib_file.exists():
            try:
                db = btp.loads(bib_file.read_text(encoding="utf-8"))
                for entry in db.entries:
                    key = entry["ID"]
                    label = key.split(":", 1)[1] if ":" in key else key
                    if label == "main":
                        continue
                    snippets[key] = {
                        "pageno": entry.get("pages", ""),
                        "text": entry.get("title", ""),
                    }
            except Exception as exc:
                logger.warning(
                    "Could not parse label.bib in %s: %s", uuid_dir.name, exc
                )

        result[info.uuid] = {
            "url": info.url,
            "title": info.title,
            "author": info.authors,
            "date": info.dates,
            "tags": info.tags,
            "snippets": snippets,
        }
    return result


def _bib_to_hayagriva(bib_text: str) -> str:
    """Convert combined BibTeX into a Hayagriva YAML bibliography.

    Hayagriva is Typst's native bibliography format: a mapping keyed by
    citation key.  Each ``@article`` entry becomes one Hayagriva entry with
    kebab-case fields.  The snippet ``journal`` field (the containing document
    title) is emitted as a ``parent`` relation.
    """
    db = btp.loads(bib_text)

    def _flat(value: str) -> str:
        """Collapse newlines and whitespace runs so scalars stay single-line."""
        return " ".join(value.split())

    out: dict[str, dict] = {}
    for entry in db.entries:
        key = entry["ID"]
        item: dict = {"type": "article"}

        title = _flat(entry.get("title", ""))
        if title:
            item["title"] = title
        author = _flat(entry.get("author", ""))
        if author:
            item["author"] = author
        date = entry.get("date", "")
        if date:
            item["date"] = date
        url = entry.get("url", "")
        if url:
            item["url"] = url
        pages = entry.get("pages", "")
        if pages:
            item["page-range"] = pages
        journal = _flat(entry.get("journal", ""))
        if journal:
            item["parent"] = {"type": "article", "title": journal}
        note = _flat(entry.get("note", ""))
        if note:
            item["note"] = note

        out[key] = item

    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=1000)


def _bib_to_markdown(
    bib_text: str, dataset: str = "", include_keys: bool = False
) -> str:
    """Convert BibTeX entries to a Markdown report.

    Groups entries by their key prefix (the part before ``:``) so that all
    snippets from the same document appear under a single ``##`` heading.
    Document-level metadata (author, date, url) is emitted once per document.
    Each snippet becomes a ``###`` sub-heading with a ``- p. X: …`` bullet.
    """
    import datetime
    from collections import OrderedDict

    db = btp.loads(bib_text)

    # Group entries by prefix (everything before the first ':' in the key).
    # Preserve document order using the first-seen prefix as the sort key.
    docs: OrderedDict[str, dict] = (
        OrderedDict()
    )  # prefix -> {"main": entry, "snippets": [entry]}
    for entry in db.entries:
        key = entry["ID"]
        if ":" in key:
            prefix, label = key.split(":", 1)
        else:
            prefix, label = key, "main"

        if prefix not in docs:
            docs[prefix] = {"main": None, "snippets": []}

        if label == "main":
            docs[prefix]["main"] = entry
        else:
            docs[prefix]["snippets"].append((label, entry))

    n_docs = len(docs)
    n_snippets = sum(len(doc["snippets"]) for doc in docs.values())
    today = datetime.date.today().isoformat()

    header = "# Label extraction"
    if dataset:
        header += f": {dataset}"
    lines = [
        f"{header}\n",
        f"- **Date**: {today}",
        f"- **Documents**: {n_docs}",
        f"- **Snippets**: {n_snippets}",
        "",
    ]

    for prefix, doc in docs.items():
        main = doc["main"]
        snippets = doc["snippets"]

        # Document header — use main title if available, else prefix
        if main is not None:
            doc_title = main.get("title", prefix)
            doc_author = main.get("author", "")
            doc_date = main.get("date", "")
            doc_url = main.get("url", "")
        elif snippets:
            # No :main entry — infer from first snippet
            _, first = snippets[0]
            doc_title = first.get("journal", prefix)
            doc_author = first.get("author", "")
            doc_date = first.get("date", "")
            doc_url = first.get("url", "")
        else:
            continue

        lines.append(f"## {doc_title}\n")
        if doc_author:
            lines.append(f"- **Author**: {doc_author}")
        if doc_date:
            lines.append(f"- **Date**: {doc_date}")
        if doc_url:
            lines.append(f"- **URL**: {doc_url}")
        lines.append("")

        for label, snippet in snippets:
            if include_keys:
                lines.append(f"  ### {label}")
            page = snippet.get("pages", "")
            text = snippet.get("title", "")
            page_prefix = f"p. {page}: " if page else ""
            indented = text.replace("\n", "\n    ")
            lines.append(f"  - {page_prefix}{indented}")
            lines.append("")

    return "\n".join(lines)
