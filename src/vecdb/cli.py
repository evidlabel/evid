"""CLI with rich metadata display from info.yml."""
import logging
from rich.console import Console
from rich.table import Table
from rich.logging import RichHandler
from treeparse import cli, command, option

from .core.db import get_client, create_collection, bulk_add_documents, query_collection
from .utils.file_utils import get_documents_with_metadata, get_label_files

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger(__name__)


def init(directory: str, collection: str = "default"):
    """Create collection."""
    client = get_client(directory)
    create_collection(client, collection)
    print(f"✅ Collection '{collection}' created in {directory}")


def add(directory: str, target_dir: str, collection: str = "default"):
    """Index label.typ files with metadata from info.yml."""
    client = get_client(directory)
    documents, metadatas, ids = get_documents_with_metadata(target_dir)
    num_files = len(get_label_files(target_dir))
    logger.info(f"Found {num_files} label.typ files → {len(documents)} chunks")
    if documents:
        bulk_add_documents(client, collection, documents, ids, metadatas)
        print(f"✅ Added {len(documents)} chunks (with URL/title metadata) to '{collection}'")


def query(directory: str, query_text: str, collection: str = "default", top_n: int = 5, full: bool = False):
    """Search and show rich results (Title + URL from info.yml)."""
    client = get_client(directory)
    results = query_collection(client, collection, query_text, n_results=top_n)

    console = Console()
    if not results or not results.get("ids") or not results["ids"][0]:
        console.print("[yellow]No results found.[/yellow]")
        return

    ids = results["ids"][0]
    documents = results["documents"][0]
    distances = results["distances"][0]
    metadatas = results.get("metadatas", [[]])[0] or [{}] * len(ids)

    table = Table(title="🔍 vecdb Results", show_lines=True)
    table.add_column("Rank", style="cyan", justify="right")
    table.add_column("Title", style="blue")
    table.add_column("URL", style="magenta")
    table.add_column("Distance", style="yellow", justify="right")
    table.add_column("Content", style="green")

    for i, (doc_id, doc, dist, meta) in enumerate(zip(ids, documents, distances, metadatas), 1):
        title = (meta.get("title") or doc_id)[:65]
        url = meta.get("url") or "─"
        content = doc if full else (doc[:140] + "…")
        table.add_row(str(i), title, url, f"{dist:.4f}", content)

    console.print(table)
    if any(m.get("url") for m in metadatas):
        console.print("\n[bold green]Tip:[/] Copy any URL above or rerun with --full (-f) for complete passages.")


init_cmd = command(
    name="init",
    help="Create collection.",
    callback=init,
    options=[
        option(flags=["--directory", "-d"], arg_type=str, required=True, help="DB directory"),
        option(flags=["--collection", "-c"], arg_type=str, default="default", help="Collection"),
    ],
)

add_cmd = command(
    name="add",
    help="Index label.typ files with metadata from info.yml.",
    callback=add,
    options=[
        option(flags=["--directory", "-d"], arg_type=str, required=True, help="DB directory"),
        option(flags=["--target-dir", "-t"], arg_type=str, required=True, help="Dir containing label.typ + info.yml"),
        option(flags=["--collection", "-c"], arg_type=str, default="default", help="Collection"),
    ],
)

query_cmd = command(
    name="query",
    help="Search and show rich results (Title + URL from info.yml).",
    callback=query,
    options=[
        option(flags=["--directory", "-d"], arg_type=str, required=True, help="DB directory"),
        option(flags=["--query-text", "-q"], arg_type=str, required=True, help="Query"),
        option(flags=["--collection", "-c"], arg_type=str, default="default", help="Collection"),
        option(flags=["--top-n", "-n"], arg_type=int, default=5, help="Results"),
        option(flags=["--full", "-f"], arg_type=bool, default=False, help="Show full passages"),
    ],
)

app = cli(
    name="vecdb",
    help="vecdb - semantic search over large datasets (label.typ + info.yml).",
    commands=[init_cmd, add_cmd, query_cmd],
)


def main():
    app.run()
