#!/usr/bin/env python3
"""Clean URL-encoded characters from evid dataset metadata.

Two-step workflow:
    python scripts/clean_metadata.py --dataset litc            # flag (dry-run)
    python scripts/clean_metadata.py --dataset litc --apply    # write changes

Scans the `title` and `label` fields in every
`{db}/{dataset}/docs/*/info.yml` and reports values that contain `%XX`
percent-encoding artifacts (typically left over when a doc was added
from a URL whose slug stood in for the page title). With --apply, the
fields are URL-decoded in place. The `url` field is intentionally never
touched — percent-encoding is valid there.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import yaml

URL_ENCODED_RE = re.compile(r"%[0-9a-fA-F]{2}")
CLEANABLE_FIELDS = ("title", "label")


def find_dataset(db_root: Path, slug: str) -> Path:
    """Locate the dataset directory under db_root.

    Tries `{db}/{slug}` and `{db}/sets/{slug}`.
    """
    for candidate in (db_root / slug, db_root / "sets" / slug):
        if (candidate / "docs").is_dir():
            return candidate
    raise SystemExit(
        f"error: dataset {slug!r} not found under {db_root} "
        f"(looked for {slug}/docs and sets/{slug}/docs)"
    )


def collect_changes(
    docs_dir: Path,
) -> list[tuple[Path, dict, dict[str, tuple[str, str]]]]:
    """For each doc, return (info_path, parsed_info, {field: (old, new)})."""
    changes = []
    for info_path in sorted(docs_dir.glob("*/info.yml")):
        with info_path.open(encoding="utf-8") as f:
            info = yaml.safe_load(f) or {}
        proposed: dict[str, tuple[str, str]] = {}
        for field in CLEANABLE_FIELDS:
            old = info.get(field, "")
            if not isinstance(old, str) or not old:
                continue
            if not URL_ENCODED_RE.search(old):
                continue
            new = unquote(old)
            if new != old:
                proposed[field] = (old, new)
        if proposed:
            changes.append((info_path, info, proposed))
    return changes


def report(changes: list, total_docs: int) -> None:
    print(f"Scanned {total_docs} doc(s); {len(changes)} need cleanup.\n")
    for info_path, info, proposed in changes:
        uuid_short = str(info.get("uuid", "?"))[:8]
        print(f"  {uuid_short}  {info_path}")
        for field, (old, new) in proposed.items():
            print(f"    {field}:")
            print(f"      - {old}")
            print(f"      + {new}")
        print()


def apply_changes(changes: list) -> int:
    written = 0
    for info_path, info, proposed in changes:
        for field, (_, new) in proposed.items():
            info[field] = new
        with info_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(info, f, allow_unicode=True, sort_keys=True)
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", required=True, help="Dataset slug")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.home() / ".local/share/evidmgr",
        help="DB root (default: ~/.local/share/evidmgr)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes back. Without this flag the script only flags.",
    )
    args = parser.parse_args()

    dataset_dir = find_dataset(args.db, args.dataset)
    docs_dir = dataset_dir / "docs"

    total = sum(1 for _ in docs_dir.glob("*/info.yml"))
    changes = collect_changes(docs_dir)

    if not changes:
        print(f"Scanned {total} doc(s); no metadata needs cleanup.")
        return 0

    report(changes, total)

    if not args.apply:
        print("Re-run with --apply to write the changes above.")
        return 0

    written = apply_changes(changes)
    print(f"Wrote {written} info.yml file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
