"""CLI callback functions."""

import json
import logging
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

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
    get_evidence_list,
    label_evidence,
    select_evidence,
)
from evid.cli.tags import assign_tag, list_tags, remove_tag, show_tag
from evid.core.bibtex import generate_bibtex
from evid.core.gather import gather_dataset
from evid.core.models import ConfigModel
from evid.core.quote_extract import (
    candidates_from_search,
    extract_quotes,
    load_quotes_json,
)
from evid.core.rebut_doc import rebut_doc
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
    """Resolve a dataset name/number to a slug, prompting interactively if needed."""
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


def create_callback(db: str = None, dataset: str = None):
    """Create a new dataset."""
    if not dataset:
        dataset = input("Enter new dataset name: ").strip()
        if not dataset:
            sys.exit("No dataset name provided.")
    create_dataset(DIRECTORY, dataset)


def track_callback(db: str = None, dataset: str = None):
    """Track a dataset with Git."""
    dataset = _resolve_dataset(dataset, "Select dataset to track")
    track_dataset(DIRECTORY, dataset)


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


# ── doc callbacks ──────────────────────────────────────────────────────────────


def add_callback(
    db: str = None,
    source: str = None,
    label: bool = False,
    autolabel: bool = False,
    dataset: str = None,
    no_index: bool = False,
):
    """Add a document to a dataset."""
    dataset = _resolve_dataset(dataset, "Select dataset for adding document")
    add_evidence(DIRECTORY, dataset, source, label, autolabel, no_index=no_index)


def bibtex_callback(db: str = None, dataset: str = None, uuid: str = None):
    """Generate BibTeX for a document."""
    dataset = _resolve_dataset(
        dataset, "Select dataset for BibTeX generation", allow_create=False
    )
    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset)
    typ_file = docs_dir(DIRECTORY, dataset) / uuid / "label.typ"
    if not typ_file.exists():
        sys.exit(f"label.typ not found in {dataset}/{uuid}")
    generate_bibtex([typ_file])


def _search_candidates(dataset: str, uuid: str, query: str, n: int):
    """Seed quote candidates from a vector search restricted to one document."""
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
):
    """Machine-extract verbatim quotes from a document into machine.hayagriva.

    Candidates come either from a JSON file (``--from``, deliberately not Hayagriva
    so the paraphrased input is never citable) or from a vector search over the set
    (``--from-search``, which seeds candidates from the top-``n`` matching chunks).
    Only the verbatim, rapidfuzz-verified output is written as Hayagriva. Prints
    citation keys only — never quote text.
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
    print(
        f"\n{n_matched}/{len(results)} quotes added to {doc_dir / 'machine.hayagriva'}"
    )
    for r in results:
        if r.matched:
            print(f"  cite as @{r.key}")


def label_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    filename: str = "label.typ",
):
    """Open a document in the labeler."""
    dataset = _resolve_dataset(dataset, "Select dataset to label", allow_create=False)
    label_evidence(DIRECTORY, dataset, uuid, filename)


def rebut_callback(db: str = None, dataset: str = None, uuid: str = None):
    """Generate a rebuttal document."""
    dataset = _resolve_dataset(
        dataset, "Select dataset for rebuttal", allow_create=False
    )
    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset, "Select document for rebuttal")
    workdir = docs_dir(DIRECTORY, dataset) / uuid
    if not workdir.exists():
        sys.exit(f"Document directory {workdir} does not exist.")
    try:
        rebut_doc(workdir)
        print(f"Rebuttal generated for {dataset}/{uuid}")
    except Exception as e:
        sys.exit(f"Failed to generate rebuttal: {e!s}")


def list_docs_callback(
    db: str = None,
    dataset: str = None,
    format: str = "table",
):
    """List documents in a dataset."""
    dataset = _resolve_dataset(dataset, "Select dataset to list", allow_create=False)
    documents = get_evidence_list(DIRECTORY, dataset)
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

    Re-chunks each doc's label.typ and replaces its existing vecdb entries.
    Needed after a chunking change so old chunks are refreshed.
    """
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
    for doc_dir in doc_dirs:
        if ingester.index_existing(doc_dir, evidence_set):
            ok += 1
    print(f"Reindexed {ok}/{len(doc_dirs)} document(s) in '{dataset}'.")


def mcp_callback(db: str = None, dataset: str = None):
    """Run the evid MCP server (stdio) — a warm query session for agents.

    Loads the embedding model once and keeps Chroma clients warm, so a sequence
    of search calls avoids the per-process cold start. The server is scoped to a
    single dataset (-s); it exposes no other set, so an attached agent cannot
    wander into other (private) sets in the same database.
    """
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


def gui_callback(db: str = None):
    """Launch the GUI."""
    try:
        from evid.gui.main_window import main as gui_main

        gui_main(DIRECTORY if DIRECTORY_EXPLICIT else None)
    except ImportError:
        print("GUI requires evid and PySide6. Install with: pip install evid pyside6")
        sys.exit(1)


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
