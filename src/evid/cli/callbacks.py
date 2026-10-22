"""CLI callback functions."""

import json
import logging
import os
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from evid import extras
from evid.cli.dataset import (
    create_dataset,
    docs_dir,
    get_datasets,
    list_datasets,
    select_dataset,
    set_dir,
    track_dataset,
)
from evid.cli.evidence import (
    add_evidence,
    add_screenshots,
    get_evidence_list,
    select_evidence,
)
from evid.cli.tags import assign_tag, list_tags, remove_tag, show_tag
from evid.config import ConfigModel
from evid.core.gather import gather_dataset
from evid.core.quote_extract import (
    candidates_from_search,
    extract_quotes,
    load_quotes_json,
)
from evid.core.quote_pass import (
    pass_summaries,
    record_pass,
    resolve_pass_meta,
)
from evid.core.share import write_share
from evid.models import Document

# Logging is configured centrally in evid.logging_config (called from main()).
logger = logging.getLogger(__name__)

DIRECTORY = None
DIRECTORY_EXPLICIT = False  # True when --db was given on the command line


# ── shared helpers ─────────────────────────────────────────────────────────────


def _resolve_dataset(
    dataset: str | None,
    prompt: str = "Select dataset",
    allow_create: bool = False,
) -> str:
    """Resolve a dataset name/number to a slug, prompting interactively if needed.

    Without -s, EVID_SET (set for the GUI's Agent pane of a set) is the default.
    """
    if not dataset:
        dataset = os.environ.get("EVID_SET") or None
    if not dataset:
        return select_dataset(DIRECTORY, prompt, allow_create=allow_create)
    if dataset.isdigit():
        datasets = sorted(get_datasets(DIRECTORY))
        idx = int(dataset) - 1
        if 0 <= idx < len(datasets):
            return datasets[idx]
        sys.exit(f"Invalid dataset number: {dataset}")
    if not set_dir(DIRECTORY, dataset).exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")
    return dataset


def _print_vec_results(
    results: list,
    fmt: str,
    query: str,
    dataset: str,
    n: int,
) -> None:
    if not results:
        print(f"No results for '{query}'.")
        return
    if fmt == "json":
        data = [
            {
                "rank": i + 1,
                "score": round(r.score, 4),
                "label": r.doc.label,
                "uuid": r.doc.uuid,
                "chunk": r.chunk_text,
                "chunk_idx": r.chunk_idx,
                "source_url": r.doc.source_url,
            }
            for i, r in enumerate(results)
        ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif fmt == "md":
        print(f'## Vector search: "{query}" — {dataset} (n={n})\n')
        for i, r in enumerate(results, 1):
            short = r.doc.uuid[:8] + "\u2026" + r.doc.uuid[-8:]
            print(f"{i}. **{r.doc.label}** `score: {r.score:.3f}` `{short}`")
            preview = r.chunk_text[:200].replace("\n", " ")
            print(f"   > {preview}\n")
    else:
        console = Console()
        table = Table(title=f'Vector search: "{query}" \u2014 {dataset}')
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("Score", justify="right", width=7)
        table.add_column("Label", ratio=3)
        table.add_column("UUID", width=20)
        table.add_column("Preview", ratio=4)
        for i, r in enumerate(results, 1):
            short = r.doc.uuid[:16] + "\u2026"
            preview = r.chunk_text[:100].replace("\n", " ")
            table.add_row(str(i), f"{r.score:.3f}", r.doc.label, short, preview)
        console.print(table)


def _print_meta_results(
    docs: list[Document],
    fmt: str,
    pattern: str,
    dataset: str,
) -> None:
    if not docs:
        print(f"No results for '{pattern}'.")
        return
    if fmt == "json":
        data = [
            {
                "uuid": d.uuid,
                "label": d.label,
                "source_url": d.source_url,
                "tags": d.tags,
            }
            for d in docs
        ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif fmt == "md":
        print(f'## Meta search: "{pattern}" \u2014 {dataset}\n')
        for i, d in enumerate(docs, 1):
            short = d.uuid[:8] + "\u2026"
            print(f"{i}. **{d.label}** `{short}`")
            if d.source_url:
                print(f"   <{d.source_url}>")
            print()
    else:
        console = Console()
        table = Table(title=f'Meta search: "{pattern}" \u2014 {dataset}')
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("UUID", width=20)
        table.add_column("Label", ratio=4)
        table.add_column("Tags")
        table.add_column("URL")
        for i, d in enumerate(docs, 1):
            short = d.uuid[:16] + "\u2026"
            table.add_row(str(i), short, d.label, ", ".join(d.tags), d.source_url or "")
        console.print(table)


def _print_text_results(
    hits: list,
    fmt: str,
    query: str,
    dataset: str,
    regex: bool,
) -> None:
    mode = "regex" if regex else "substring"
    if not hits:
        print(f"No full-text ({mode}) results for '{query}'.")
        return
    if fmt == "json":
        data = [
            {
                "uuid": h.uuid,
                "label": h.label,
                "page": h.page,
                "char_start": h.char_start,
                "snippet": h.snippet,
            }
            for h in hits
        ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif fmt == "md":
        print(f'## Full-text {mode} search: "{query}" — {dataset}\n')
        for i, h in enumerate(hits, 1):
            short = h.uuid[:8] + "…"
            print(f"{i}. **{h.label}** `p.{h.page}` `{short}`")
            print(f"   > {h.snippet}\n")
    else:
        console = Console()
        title = f'Full-text {mode} search: "{query}" — {dataset}'
        table = Table(title=title)
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("Page", justify="right", width=5)
        table.add_column("Label", ratio=3)
        table.add_column("Snippet", ratio=5)
        for i, h in enumerate(hits, 1):
            table.add_row(str(i), str(h.page), h.label, h.snippet[:160])
        console.print(table)


# ── set callbacks ──────────────────────────────────────────────────────────────


def create_callback(db: str = None, dataset: str = None, type: str = "normal"):
    """Create a new dataset."""
    if not dataset:
        dataset = input("Enter new dataset name: ").strip()
        if not dataset:
            sys.exit("No dataset name provided.")
    create_dataset(DIRECTORY, dataset, type)


def track_callback(db: str = None, dataset: str = None):
    """Track a dataset with Git."""
    dataset = _resolve_dataset(dataset, "Select dataset to track")
    track_dataset(DIRECTORY, dataset)


def _migrate_progress(result) -> None:
    """One line per document so a long set is not silent until the final table."""
    if result.skipped and not result.error:
        return
    name = result.title or result.uuid[:8]
    if result.error:
        print(f"  {name}: {result.error}", flush=True)
        return
    print(
        f"  {name}: {result.placed} placed, {result.fuzzy} fuzzy, {result.unplaced} unplaced"
        + (", text written" if result.text else ""),
        flush=True,
    )


def migrate_labels_callback(db: str = None, dataset: str = None, dry_run: bool = False):
    """Move a set's label.typ labels and machine quotes onto label/ spans."""
    from rich.console import Console
    from rich.table import Table

    from evid.services.migrate_labels import migrate_set

    dataset = _resolve_dataset(dataset, "Select dataset to migrate", allow_create=False)
    print(f"migrate-labels: {dataset}", flush=True)
    report = migrate_set(DIRECTORY, dataset, dry_run=dry_run, on_doc=_migrate_progress)
    table = Table(
        title=f"migrate-labels: {dataset}" + (" (dry run)" if dry_run else "")
    )
    table.add_column("document")
    table.add_column("placed", justify="right")
    table.add_column("fuzzy", justify="right")
    table.add_column("unplaced", justify="right")
    table.add_column("quotes", justify="right")
    table.add_column("note")
    shown = [d for d in report.docs if d.skipped != "no old labels"]
    for d in shown:
        name = d.title or d.uuid[:8]
        note = d.error or d.skipped
        if d.already:
            note = (note + "; " if note else "") + f"{d.already} already there"
        if d.quotes_moved:
            note = (note + "; " if note else "") + f"{d.quotes_moved} re-anchored"
        table.add_row(
            name,
            str(d.placed),
            str(d.fuzzy),
            str(d.unplaced),
            str(d.quotes + d.quotes_moved),
            note,
        )
    console = Console()
    if shown:
        console.print(table)
    else:
        print(f"No old labels in {dataset}.")
    for d in shown:
        if not d.details:
            continue
        who = d.title or d.uuid[:8]
        print(f"Unplaced in {who}:")
        for line in d.details:
            print(f"  {line}")
    labels = sum(d.placed + d.fuzzy for d in report.touched)
    unplaced = sum(d.unplaced for d in report.touched)
    if dry_run:
        print(
            f"Dry run: {labels} labels would be placed, {unplaced} left unplaced. Nothing written."
        )
    elif report.commit and report.touched:
        print(
            f"Committed {report.commit}: {labels} labels placed, {unplaced} unplaced."
        )
    elif report.commit:
        print(f"Committed {report.commit}: recorded the archived label files.")
    elif report.commit_error:
        print(
            f"Migrated {len(report.touched)} documents ({labels} labels, {unplaced} unplaced). "
            f"Git did not commit: {report.commit_error}"
        )
    elif report.touched:
        print(
            f"Migrated {len(report.touched)} documents ({labels} labels, {unplaced} unplaced)."
        )


def list_datasets_callback(db: str = None):
    """List all available datasets."""
    list_datasets(DIRECTORY)


def gather_callback(
    db: str = None,
    dataset: str = None,
    output: str = None,
    no_regen: bool = False,
    include_keys: bool = False,
    since: str = None,
    until: str = None,
):
    """Gather all BibTeX from a dataset into a single output file."""
    dataset = _resolve_dataset(dataset, "Select dataset to gather", allow_create=False)
    if not output:
        sys.exit("--output / -o is required.")
    gather_dataset(
        DIRECTORY,
        dataset,
        Path(output).expanduser(),
        regen=not no_regen,
        include_keys=include_keys,
        since=since,
        until=until,
    )


def share_callback(db: str = None, dataset: str = None, output: str = None):
    """Write a json.gz catalog of this set's public documents.

    Each kept document has its url, tags, labels, and the sha256 of the PDF
    and of the canonical text when those files exist. A document with no
    http(s) url is left out.
    """
    dataset = _resolve_dataset(dataset, "Select dataset to share", allow_create=False)
    if not output:
        sys.exit("--output / -o is required.")
    dest = Path(output).expanduser()
    kept, dropped = write_share(set_dir(DIRECTORY, dataset), dataset, dest)
    print(
        f"Wrote {dest} ({kept} document(s), {dropped} without a public URL left out)."
    )


def merge_refs_callback(
    db: str = None, inputs: str | list[str] = None, output: str = None
):
    """Merge gathered Hayagriva .yml files into one store."""
    from evid.core.gather import merge_hayagriva

    if not output:
        sys.exit("--output / -o is required.")
    paths = [Path(p).expanduser() for p in (inputs or [])]
    if not paths:
        sys.exit("give at least one gathered .yml to merge.")
    out = Path(output).expanduser()
    merged = merge_hayagriva(paths, out)
    print(f"merged {len(paths)} file(s) → {out} ({len(merged)} entries)")


# ── doc callbacks ──────────────────────────────────────────────────────────────


def add_callback(
    db: str = None,
    source: str | list[str] = None,
    label: bool = False,
    autolabel: bool = False,
    dataset: str = None,
    no_index: bool = False,
):
    """Add one or more documents (PDFs, a directory, or URLs) to a dataset."""
    dataset = _resolve_dataset(dataset, "Select dataset for adding document")
    add_evidence(DIRECTORY, dataset, source, label, autolabel, no_index=no_index)


def screenshot_callback(
    db: str = None,
    source: str | list[str] = None,
    dataset: str = None,
    title: str = "",
    authors: str = "",
    dates: str = "",
    url: str = "",
    lang: str = "dan+eng",
    no_index: bool = False,
):
    """Add screenshots as one document. Each image is a page; the text is OCR."""
    dataset = _resolve_dataset(dataset, "Select dataset for adding screenshots")
    sources = source if isinstance(source, (list, tuple)) else [source]
    add_screenshots(
        DIRECTORY,
        dataset,
        [s for s in sources if s],
        title=title or "",
        authors=authors or "",
        dates=dates or "",
        url=url or "",
        lang=lang or "dan+eng",
        no_index=no_index,
    )


def _have_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _search_candidates(dataset: str, uuid: str, query: str, n: int):
    """Seed quote candidates from a vector search restricted to one document."""
    if not extras.has_vec():
        print(extras.VEC_INSTALL)
        sys.exit(1)
    from evid.services.set_manager import SetManager
    from evid.services.vec_service import VecService

    try:
        evidence_set = SetManager(DIRECTORY).load_set(dataset)
    except FileNotFoundError:
        sys.exit(f"Dataset '{dataset}' not found.")
    try:
        # Over-fetch, then filter to the target document and cap at n.
        results = VecService().query(evidence_set, query, n_results=max(n * 3, n))
    except Exception as exc:
        sys.exit(f"Vector search failed: {exc}")
    return candidates_from_search(results, uuid, n)


def quote_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    from_path: str = None,
    from_search: str = None,
    n: int = 5,
    min_ratio: float = 0.78,
    refresh: bool = False,
    model: str = None,
    job: str = None,
):
    """Machine-extract verbatim quotes from a document into a pass (``pass/``).

    Candidates come either from a JSON file (``--from``, deliberately not Hayagriva
    so the paraphrased input is never citable) or from a vector search over the set
    (``--from-search``, which seeds candidates from the top-``n`` matching chunks).
    Only verbatim, rapidfuzz-verified passages are kept: each found quote is a
    span over the document's canonical text (``label/text.txt``). Every invocation
    writes one pass under ``pass/`` (timestamp, job description, model, outcomes,
    the spans), committed when the set is in git. Gather turns passes into
    Hayagriva. Prints citation keys only — never quote text.
    """
    dataset = _resolve_dataset(dataset, "Select dataset to quote", allow_create=False)
    if bool(from_path) == bool(from_search):
        sys.exit(
            "Provide exactly one of --from (quotes.json) or --from-search <query>."
        )
    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset, "Select document to quote")
    doc_dir = docs_dir(DIRECTORY, dataset) / uuid
    if not doc_dir.exists():
        sys.exit(f"Document directory {doc_dir} does not exist.")

    quotes_file = None
    if from_search:
        candidates = _search_candidates(dataset, uuid, from_search, n)
        if not candidates:
            sys.exit(
                f"Vector search for '{from_search}' returned no chunks for {uuid}. "
                "Is the document indexed? (added without --no-index)"
            )
        print(
            f'Seeding candidates from vector search: "{from_search}" (top {len(candidates)})'
        )
    else:
        try:
            quotes_file = load_quotes_json(Path(from_path).expanduser())
        except (ValueError, OSError) as exc:
            sys.exit(f"Could not load quotes JSON: {exc}")
        candidates = quotes_file.quotes
        if not candidates:
            sys.exit(f"No candidates found in {from_path}.")

    try:
        results = extract_quotes(
            doc_dir, candidates, min_ratio=min_ratio, refresh=refresh
        )
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"Quote extraction failed: {exc}")

    job_text, model_name = resolve_pass_meta(
        job=job,
        model=model,
        from_search=from_search,
        quotes_file=quotes_file,
    )
    pass_path = record_pass(
        doc_dir,
        job=job_text,
        model=model_name,
        quotes=candidates,
        results=results,
    )

    console = Console()
    table = Table(title=f"quote: {dataset}/{uuid}", show_header=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Result")
    table.add_column("Key")
    for i, r in enumerate(results, 1):
        if r.matched:
            table.add_row(str(i), f"{r.score:.2f}", "matched", r.key)
        else:
            table.add_row(str(i), f"{r.score:.2f}", "skipped (low confidence)", "—")
    console.print(table)

    n_matched = sum(1 for r in results if r.matched)
    print(f"\n{n_matched}/{len(results)} quotes found")
    print(f"pass recorded at {pass_path}")
    from evid.core.bibtex_utils import load_title
    from evid.core.gitops import commit_labels

    title = load_title(doc_dir / "info.yml") or uuid[:8]
    commit_labels(
        doc_dir, f"pass: {title} — {job_text or 'quotes'} (+{n_matched} quotes)"
    )
    for r in results:
        if r.matched:
            print(f"  cite as @{r.key}")


def passes_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    format: str = "table",
):
    """List machine-quote passes for a document (no quote text)."""
    dataset = _resolve_dataset(dataset, "Select dataset", allow_create=False)
    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset, "Select document")
    doc_dir = docs_dir(DIRECTORY, dataset) / uuid
    if not doc_dir.exists():
        sys.exit(f"Document directory {doc_dir} does not exist.")

    summaries = pass_summaries(doc_dir)
    if not summaries:
        print(f"No machine passes in {dataset}/{uuid}.")
        return
    if format == "json":
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
        return
    if format == "md":
        print(f"## Machine passes — {dataset}/{uuid}\n")
        for s in summaries:
            matched = s["matched"]
            tried = s["tried"]
            model = s["model"] or "—"
            job = s["job"] or "—"
            print(f"- `{s['key']}` `{s['id']}` **{model}** {matched}/{tried} — {job}")
        return

    console = Console()
    table = Table(title=f"passes: {dataset}/{uuid}", show_header=True)
    table.add_column("Key")
    table.add_column("When")
    table.add_column("Model")
    table.add_column("Matched", justify="right")
    table.add_column("Job")
    for s in summaries:
        table.add_row(
            s["key"],
            s["timestamp"],
            s["model"] or "—",
            f"{s['matched']}/{s['tried']}",
            s["job"] or "—",
        )
    console.print(table)


def label_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
):
    """Open a document in the GUI label pane.

    With no display, print how to label it from ``evid label`` instead.
    """
    dataset = _resolve_dataset(dataset, "Select dataset to label", allow_create=False)
    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset, "Select document to label")
    doc_dir = docs_dir(DIRECTORY, dataset) / uuid
    if not doc_dir.is_dir():
        sys.exit(f"No document {uuid!r} in '{dataset}'.")
    if not _have_display():
        print(f"No display, so the label pane stays closed. Label {dataset}/{uuid}:")
        print(f'  evid label add -s {dataset} -u {uuid} --text "verbatim passage"')
        print(f"  evid label ls -s {dataset} -u {uuid}")
        print(f"  evid label text -s {dataset} -u {uuid}")
        return
    from evid.config import EvidConfig
    from evid.web.server import serve_gui

    print(f"Opening {dataset}/{uuid} in the label pane.")
    config = EvidConfig.load()
    config.data_dir = Path(DIRECTORY)
    serve_gui(config, open_at={"set": dataset, "doc": uuid, "pane": "label"})


def list_docs_callback(
    db: str = None,
    dataset: str = None,
    format: str = "table",
):
    """List documents in a dataset."""
    dataset = _resolve_dataset(dataset, "Select dataset to list", allow_create=False)
    documents = get_evidence_list(DIRECTORY, dataset)
    if not documents and format == "json":
        print("[]")  # JSON stays JSON, so a script reading it sees an empty list
        return
    if not documents:
        print("No documents found.")
        return
    if format == "json":
        print(json.dumps(documents, ensure_ascii=False, indent=2))
    elif format == "md":
        print(f"## Documents \u2014 {dataset}\n")
        for i, ev in enumerate(documents, 1):
            print(f"{i}. **{ev['title']}** `{ev['uuid'][:8]}\u2026` ({ev['date']})")
    else:
        console = Console()
        table = Table(title=f"Documents in {dataset}")
        table.add_column("Nr", justify="right")
        table.add_column("Date")
        table.add_column("UUID")
        table.add_column("Label")
        for i, ev in enumerate(documents, 1):
            table.add_row(str(i), ev["date"], ev["uuid"], ev["title"])
        console.print(table)


def _doc_dir_or_exit(dataset: str, uuid: str) -> Path:
    doc_dir = docs_dir(DIRECTORY, dataset) / uuid
    if not uuid or not doc_dir.is_dir():
        sys.exit(f"No document {uuid!r} in '{dataset}'.")
    return doc_dir


def _is_doc_path(path: str | None) -> bool:
    raw = (path if path is not None else ".").replace("\\", "/").strip()
    return raw in ("", ".", "./")


def _document_blocks(doc_dir: Path) -> list[str]:
    """Printable whole-document notes, oldest first, plus a legacy note not yet moved."""
    from evid.core.annotations import read_annotations
    from evid.core.labels import notes_text, read

    blocks = []
    seen: set[str] = set()
    for rec in read(doc_dir).get("document") or []:
        if not isinstance(rec, dict):
            continue
        text = notes_text(rec)
        if rec.get("kind") == "label" and rec.get("key"):
            blocks.append(
                f"[{rec['key']}] {text}".rstrip() if text else f"[{rec['key']}]"
            )
        elif text:
            blocks.append(text)
        else:
            continue
        if text:
            seen.add(text.strip())
    legacy = (read_annotations(doc_dir).get(".") or "").strip()
    if legacy and legacy not in seen:
        blocks.append(legacy)
    return blocks


def _print_note_blocks(blocks: list[str]) -> None:
    for block in blocks:
        for line in block.splitlines() or [""]:
            print(f"  {line}")


def note_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    path: str = None,
    text: str = None,
    clear: bool = False,
):
    """Show or add a whole-document annotation, or show or set a file note."""
    from evid.core.annotations import read_annotations, write_annotation
    from evid.core.bibtex_utils import load_title
    from evid.core.gitops import commit_labels
    from evid.core.labels import (
        add_document_annotation,
        adopt_legacy_document_note,
        clear_document_annotations,
    )

    dataset = _resolve_dataset(dataset, "Select dataset", allow_create=False)
    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset)
    doc_dir = _doc_dir_or_exit(dataset, uuid)
    try:
        if text is not None or clear:
            if _is_doc_path(path):
                if clear or not (text or "").strip():
                    write_annotation(doc_dir, ".", "")
                    clear_document_annotations(doc_dir)
                    title = load_title(doc_dir / "info.yml") or doc_dir.name[:8]
                    commit_labels(doc_dir, f"label: {title} (-document notes)")
                    print("Removed the note on .")
                    return
                adopt_legacy_document_note(doc_dir)
                rec = add_document_annotation(doc_dir, text)
                title = load_title(doc_dir / "info.yml") or doc_dir.name[:8]
                commit_labels(doc_dir, f"label: {title} (+document {rec['id']})")
                print("Added a note on .")
                return
            write_annotation(doc_dir, path or ".", "" if clear else text)
            where = path or "."
            print(
                f"{'Removed' if clear or not (text or '').strip() else 'Set'} the note on {where}"
            )
            return
        if path is not None and _is_doc_path(path):
            blocks = _document_blocks(doc_dir)
            if not blocks:
                sys.exit(1)
            print("\n".join(blocks))
            return
        notes = read_annotations(doc_dir)
    except (ValueError, FileNotFoundError) as exc:
        sys.exit(str(exc))
    if path is not None:
        note = notes.get(path.strip("/") or ".", notes.get(path))
        if note is None:
            sys.exit(1)
        print(note)
        return
    blocks = _document_blocks(doc_dir)
    if blocks:
        print(".:")
        _print_note_blocks(blocks)
    for key, note in notes.items():
        if key == ".":
            continue
        print(f"{key}:")
        _print_note_blocks([note])


def notes_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    format: str = "table",
):
    """List whole-document labels and annotations, and notes on files."""
    from evid.core.annotations import note_rows

    dataset = _resolve_dataset(dataset, "Select dataset", allow_create=False)
    docs = get_evidence_list(DIRECTORY, dataset)
    if uuid:
        docs = [d for d in docs if d["uuid"] == uuid]
        if not docs:
            sys.exit(f"No document {uuid!r} in '{dataset}'.")
    rows = []
    for doc in docs:
        doc_dir = docs_dir(DIRECTORY, dataset) / doc["uuid"]
        rows.extend(
            {"uuid": doc["uuid"], "title": doc["title"], **row}
            for row in note_rows(doc_dir)
        )
    if format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No annotations.")
        return
    if format == "md":
        last = None
        for r in rows:
            if r["uuid"] != last:
                print(f"\n## {r['title']} `{r['uuid']}`\n")
                last = r["uuid"]
            if r["path"] == ".":
                where = f"document `{r['key']}`" if r.get("key") else "document"
            else:
                where = f"`{r['path']}`" + (" (missing)" if r["missing"] else "")
            print(f"- {where}: " + r["note"].replace("\n", "\n  "))
        return
    table = Table(title=f"Annotations in {dataset}")
    table.add_column("UUID")
    table.add_column("Title")
    table.add_column("Path")
    table.add_column("Note")
    for r in rows:
        table.add_row(
            r["uuid"][:8],
            r["title"],
            r["path"] + (" (missing)" if r["missing"] else ""),
            r["note"],
        )
    Console().print(table)


# ── requests to the agent (evid fb) ───────────────────────────────────────────


def _fb_set(dataset: str | None) -> Path:
    dataset = _resolve_dataset(dataset, "Select dataset", allow_create=False)
    return set_dir(DIRECTORY, dataset)


def _fb_slug(sdir: Path) -> str:
    """Slug of a set directory. The directory name is ``plain_set_<slug>``."""
    from evid.services.layout import read_slug

    return read_slug(sdir) or sdir.name


def fb_ls_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    all: bool = False,
    format: str = "table",
):
    """List requests to the agent: open ones, or all with --all."""
    from evid.core import feedback

    sdir = _fb_set(dataset)
    titles = {
        d["uuid"]: d["title"] for d in get_evidence_list(DIRECTORY, _fb_slug(sdir))
    }
    items = [
        x
        for x in feedback.read(sdir)
        if (all or x.get("status") != "done")
        and (not uuid or x["uuid"].startswith(uuid))
    ]
    if format == "json":
        print(
            json.dumps(
                [{**x, "title": titles.get(x["uuid"], "")} for x in items],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not items:
        print("No open requests." if not all else "No requests.")
        return
    for x in items:
        where = "" if x.get("path", ".") == "." else f"  file {x['path']}"
        print(
            f"#{x['id']}  {x.get('status', 'open')}  {titles.get(x['uuid'], '')} ({x['uuid']}){where}"
        )
        for line in x["text"].splitlines():
            print(f"    {line}")
        if x.get("reply"):
            print("    reply: " + "\n           ".join(x["reply"].splitlines()))
        print()


def fb_reply_callback(
    db: str = None,
    dataset: str = None,
    id: int = None,
    text: str = None,
    done: bool = False,
):
    """Answer request ID; --done also closes it."""
    from evid.core import feedback

    try:
        feedback.update(
            _fb_set(dataset), id, reply=text, status="done" if done else None
        )
    except (KeyError, ValueError) as exc:
        sys.exit(str(exc).strip("'\""))
    print(f"Answered #{id}" + (" and closed it" if done else ""))


def fb_add_callback(
    db: str = None,
    dataset: str = None,
    text: str = None,
    uuid: str = None,
    path: str = None,
):
    """Ask something about a document (or a file of it)."""
    from evid.core import feedback

    sdir = _fb_set(dataset)
    if not uuid:
        uuid = select_evidence(DIRECTORY, _fb_slug(sdir))
    doc_dir = _doc_dir_or_exit(_fb_slug(sdir), uuid)
    if path and path != "." and not (doc_dir / path).exists():
        sys.exit(f"No file {path} in the document.")
    try:
        item = feedback.add(sdir, uuid, text or "", path or ".")
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"#{item['id']}")


def _fb_status(dataset, id, status):
    from evid.core import feedback

    try:
        feedback.update(_fb_set(dataset), id, status=status)
    except KeyError as exc:
        sys.exit(str(exc).strip("'\""))


def fb_done_callback(db: str = None, dataset: str = None, id: int = None):
    """Close request ID."""
    _fb_status(dataset, id, "done")


def fb_reopen_callback(db: str = None, dataset: str = None, id: int = None):
    """Open request ID again."""
    _fb_status(dataset, id, "open")


def fb_rm_callback(db: str = None, dataset: str = None, id: int = None):
    """Delete request ID."""
    from evid.core import feedback

    try:
        feedback.delete(_fb_set(dataset), id)
    except KeyError as exc:
        sys.exit(str(exc).strip("'\""))


# ── tag callbacks ──────────────────────────────────────────────────────────────


def tag_list_callback(db: str = None, dataset: str = None, format: str = "table"):
    """List all tags with doc and snippet counts."""
    tags = list_tags(DIRECTORY, dataset or None)
    if not tags:
        print("No tags found.")
        return
    if format == "json":
        print(json.dumps(tags, ensure_ascii=False, indent=2))
    elif format == "md":
        title = f"## Tags{' \u2014 ' + dataset if dataset else ''}\n"
        print(title)
        for tag, counts in sorted(tags.items(), key=lambda x: (-x[1]["docs"], x[0])):
            print(f"- **{tag}** ({counts['docs']} docs, {counts['snippets']} snippets)")
    else:
        console = Console()
        table = Table(title="Tags" + (f" \u2014 {dataset}" if dataset else ""))
        table.add_column("Tag")
        table.add_column("Docs", justify="right")
        table.add_column("Snippets", justify="right")
        for tag, counts in sorted(tags.items(), key=lambda x: (-x[1]["docs"], x[0])):
            table.add_row(tag, str(counts["docs"]), str(counts["snippets"]))
        console.print(table)


def tag_show_callback(
    db: str = None,
    tag: str = None,
    dataset: str = None,
    format: str = "table",
):
    """Show all docs carrying a given tag."""
    if not tag:
        sys.exit("TAG argument is required.")
    docs = show_tag(DIRECTORY, tag, dataset or None)
    if not docs:
        print(f"No documents found with tag '{tag}'.")
        return
    if format == "json":
        print(json.dumps(docs, ensure_ascii=False, indent=2))
    elif format == "md":
        print(f"## Tag: {tag}\n")
        for d in docs:
            print(f"- **{d['label']}** `{d['uuid'][:8]}\u2026` ({d['slug']})")
            if d["url"]:
                print(f"  <{d['url']}>")
    else:
        console = Console()
        table = Table(title=f"Tag: {tag}")
        table.add_column("UUID")
        table.add_column("Dataset")
        table.add_column("Snippets", justify="right")
        table.add_column("Label")
        table.add_column("URL")
        for doc in docs:
            uuid_link = f"[link=vscode://file/{doc['path']}]{doc['uuid'][:8]}[/link]"
            table.add_row(
                uuid_link, doc["slug"], doc["snippets"], doc["label"], doc["url"]
            )
        console.print(table)


def tag_assign_callback(db: str = None, uuid: str = None, tag: str = None):
    """Add a tag to a document by UUID."""
    if not uuid or not tag:
        sys.exit("Both UUID and TAG arguments are required.")
    ok, msg = assign_tag(DIRECTORY, uuid, tag)
    if ok:
        print(msg)
    else:
        sys.exit(msg)


def tag_remove_callback(db: str = None, tag: str = None, dataset: str = None):
    """Remove a tag from all documents that carry it."""
    if not tag:
        sys.exit("TAG argument is required.")
    ok, msg = remove_tag(DIRECTORY, tag, dataset=dataset)
    if ok:
        print(msg)
    else:
        sys.exit(msg)


# ── search callbacks ───────────────────────────────────────────────────────────


def search_vec_callback(
    db: str = None,
    query: str = None,
    dataset: str = None,
    n: int = 10,
    tag: str = None,
    format: str = "table",
):
    """Run a semantic vector search."""
    if not extras.has_vec():
        print(extras.VEC_INSTALL)
        sys.exit(1)
    if not query:
        sys.exit("QUERY argument is required.")
    dataset = _resolve_dataset(dataset, "Select dataset to search", allow_create=False)

    from evid.services.set_manager import SetManager
    from evid.services.vec_service import VecService

    try:
        evidence_set = SetManager(DIRECTORY).load_set(dataset)
    except FileNotFoundError:
        sys.exit(f"Dataset '{dataset}' not found.")

    try:
        results = VecService().query(
            evidence_set,
            query,
            n_results=n,
            filter_tags=[tag] if tag else None,
        )
    except Exception as exc:
        sys.exit(f"Vector search failed: {exc}")

    _print_vec_results(results, fmt=format, query=query, dataset=dataset, n=n)


def search_meta_callback(
    db: str = None,
    pattern: str = None,
    dataset: str = None,
    format: str = "table",
):
    """Run a regex search over document metadata (info.yml fields)."""
    if not pattern:
        sys.exit("PATTERN argument is required.")
    dataset = _resolve_dataset(dataset, "Select dataset to search", allow_create=False)

    from evid.core.doc_loader import search_meta_documents

    set_path = set_dir(DIRECTORY, dataset)
    results = search_meta_documents(set_path, pattern)
    _print_meta_results(results, fmt=format, pattern=pattern, dataset=dataset)


def search_text_callback(
    db: str = None,
    query: str = None,
    dataset: str = None,
    regex: bool = False,
    n: int = 10,
    context: int = 160,
    format: str = "table",
):
    """Full-text search over document bodies (substring by default, or --regex)."""
    if not query:
        sys.exit("QUERY argument is required.")
    dataset = _resolve_dataset(dataset, "Select dataset to search", allow_create=False)

    from evid.core.fulltext import search_fulltext

    set_path = set_dir(DIRECTORY, dataset)
    try:
        hits = search_fulltext(
            set_path,
            query,
            regex=regex,
            n=n,
            context=context,
        )
    except ValueError as exc:
        sys.exit(str(exc))
    _print_text_results(hits, fmt=format, query=query, dataset=dataset, regex=regex)


def reindex_callback(db: str = None, dataset: str = None):
    """Rebuild the vector index for every document in a set.

    Re-chunks each doc's canonical text (label/text.txt) and replaces its
    existing vecdb entries. Needed after a chunking change, and after
    migrating to evid 0.7 (chunk offsets now point into label/text.txt).
    """
    if not extras.has_vec():
        print(extras.VEC_INSTALL)
        sys.exit(1)
    dataset = _resolve_dataset(dataset, "Select dataset to reindex", allow_create=False)

    from evid.services.doc_ingester import DocIngester
    from evid.services.set_manager import SetManager
    from evid.services.vec_service import VecService

    try:
        evidence_set = SetManager(DIRECTORY).load_set(dataset)
    except FileNotFoundError:
        sys.exit(f"Dataset '{dataset}' not found.")

    ingester = DocIngester(vec_service=VecService())
    docs_dir = evidence_set.path / "docs"
    doc_dirs = sorted(d for d in docs_dir.iterdir() if d.is_dir())
    ok = 0
    # One long-lived index child for the whole set: the embedding model loads
    # once instead of once per document.
    from evid.vec.safe_index import IndexWorkerPool

    with IndexWorkerPool() as pool:
        for doc_dir in doc_dirs:
            if ingester.index_existing(doc_dir, evidence_set, pool=pool):
                ok += 1
    print(f"Reindexed {ok}/{len(doc_dirs)} document(s) in '{dataset}'.")


def mcp_callback(db: str = None, dataset: str = None):
    """Run the evid MCP server (stdio) — a warm query session for agents.

    Loads the embedding model once and keeps Chroma clients warm, so a sequence
    of search calls avoids the per-process cold start. The server is scoped to a
    single dataset (-s); it exposes no other set, so an attached agent cannot
    wander into other (private) sets in the same database.
    """
    dataset = dataset or os.environ.get("EVID_SET")
    if not dataset:
        sys.exit(
            "`evid mcp <dataset>` requires a dataset — the server is scoped to one "
            "set so an attached agent cannot reach other sets."
        )
    dataset = _resolve_dataset(dataset, allow_create=False)
    from evid.mcpserver import serve

    try:
        serve(DIRECTORY, dataset)
    except ValueError as exc:
        sys.exit(str(exc))


# ── other callbacks ────────────────────────────────────────────────────────────


def gui_callback(
    db: str = None,
    workdir: str = None,
    port: int = 8790,
    browser: bool = False,
    headless: bool = False,
    replace: bool = False,
    agent: str = None,
):
    """Launch the GUI (evid-app window, else the browser).

    Optional *workdir* chdirs the process before the GUI starts, so the file
    picker and relative paths resolve from that directory.
    """
    if workdir is not None:
        path = Path(workdir).expanduser().resolve()
        if not path.is_dir():
            sys.exit(f"workdir is not a directory: {path}")
        os.chdir(path)
    from evid.config import EvidConfig
    from evid.web.server import serve_gui

    config = EvidConfig.load()
    config.data_dir = Path(DIRECTORY)
    serve_gui(
        config,
        port=port or 8790,
        browser=browser,
        headless=headless,
        replace=replace,
        agent=agent or "",
    )


def update_callback(db: str = None):
    """Update configuration file."""
    config_path = Path.home() / ".evidrc"
    if config_path.exists():
        try:
            with config_path.open("r") as f:
                user_config = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            user_config = {}
            print("Invalid YAML in .evidrc, starting fresh.")
    else:
        user_config = {}

    try:
        config_model = ConfigModel(**user_config)
    except ValueError:
        default_config = ConfigModel().model_dump()
        merged = {**default_config, **user_config}
        config_model = ConfigModel(**merged)

    config = config_model.model_dump()
    with config_path.open("w") as f:
        yaml.dump(config, f, allow_unicode=True)
    print(f".evidrc updated at {config_path}.")


def show_callback(db: str = None):
    """Show current configuration."""
    config_path = Path.home() / ".evidrc"
    defaults = ConfigModel().model_dump()
    user_config = {}
    if config_path.exists():
        try:
            with config_path.open("r") as f:
                user_config = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            print("Invalid YAML in .evidrc, using defaults.")

    try:
        config_model = ConfigModel(**user_config)
        merged = config_model.model_dump()
    except ValueError:
        merged = {**defaults, **user_config}
        config_model = ConfigModel(**merged)
        merged = config_model.model_dump()

    print(
        f"Config file: {config_path if config_path.exists() else 'Not found, using defaults'}"
    )
    for key, value in merged.items():
        if key in user_config and user_config[key] != defaults.get(key):
            source = f"overridden in {config_path}"
        else:
            source = "default"
        print(f"  {key}: {value} ({source})")


def replace_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    source: str = None,
    map: str = None,
    format: str = "table",
):
    """Replace a document's PDF in place; its labels and quotes follow (did re-handoff)."""
    from evid.services.doc_replace import replace

    dataset = _resolve_dataset(dataset, "Select dataset")
    doc_dir = _doc_dir_or_exit(dataset, uuid or "")
    mapping = {}
    if map:
        try:
            mapping = json.loads(Path(map).read_text(encoding="utf-8")) or {}
        except (OSError, ValueError) as e:
            sys.exit(f"--map {map}: {e}")
    try:
        result = replace(doc_dir, Path(source or ""), mapping)
    except FileNotFoundError as e:
        sys.exit(str(e))
    if format == "json":
        print(json.dumps(result, ensure_ascii=False))
        return
    counts = (
        ", ".join(f"{n} {k}" for k, n in sorted(result["counts"].items()))
        or "no labels"
    )
    print(f"Replaced {uuid[:8]}: {counts}; {result['stale']} stale")


def stale_callback(
    db: str = None, dataset: str = None, uuid: str = None, format: str = "table"
):
    """Labels and quotes that lost their place (after a replace), per document."""
    from evid.cli.dataset import set_dir
    from evid.services.doc_replace import stale

    dataset = _resolve_dataset(dataset, "Select dataset")
    rows = stale(set_dir(DIRECTORY, dataset), uuid)
    if format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("Nothing stale.")
    for d in rows:
        print(f"{d['uuid'][:8]}  {d['title']}")
        for r in d["records"]:
            print(f"    {r['kind']:<10} {r['key'] or '':<20} {r['text'][:70]!r}")


def repair_callback(db: str = None, dataset: str = None, uuid: str = None):
    """Ask a model where each stale label now points; keep only verbatim matches."""
    from evid.cli.dataset import set_dir
    from evid.services.doc_replace import repair, stale

    dataset = _resolve_dataset(dataset, "Select dataset")
    rows = stale(set_dir(DIRECTORY, dataset), uuid)
    if not rows:
        print("Nothing stale.")
        return
    for d in rows:
        try:
            r = repair(docs_dir(DIRECTORY, dataset) / d["uuid"])
        except RuntimeError as e:
            sys.exit(str(e))
        print(f"{d['uuid'][:8]}  {r['repaired']} re-anchored, {r['stale']} still stale")
