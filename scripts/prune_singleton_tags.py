#!/usr/bin/env python3
"""Remove tags with only one document from the litc dataset.

Usage:
    uv run python scripts/prune_singleton_tags.py [--dataset litc] [--db PATH]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages/evid/src"))

from evid.cli.tags import list_tags, remove_tag
from evid.config import EvidConfig

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dataset", default="litc")
parser.add_argument("--db", default=None)
args = parser.parse_args()

directory = Path(args.db).expanduser() if args.db else EvidConfig.load().data_dir

tags = list_tags(directory, dataset=args.dataset)
singletons = {tag: info for tag, info in tags.items() if info["docs"] == 1}

if not tags:
    print(f"No tags found in dataset '{args.dataset}'.")
    sys.exit(0)

print(f"All tags in '{args.dataset}':\n")
for tag, info in sorted(tags.items(), key=lambda x: -x[1]["docs"]):
    marker = "  <-- singleton" if tag in singletons else ""
    print(f"  {tag:40s}  docs={info['docs']}  snippets={info['snippets']}{marker}")

if not singletons:
    print("\nNo singleton tags to remove.")
    sys.exit(0)

print(f"\n{len(singletons)} singleton tag(s) will be removed:")
for tag in sorted(singletons):
    print(f"  - {tag}")

answer = input("\nProceed? [y/N] ").strip().lower()
if answer != "y":
    print("Aborted.")
    sys.exit(0)

for tag in sorted(singletons):
    ok, msg = remove_tag(directory, tag, dataset=args.dataset)
    print(msg if ok else f"ERROR: {msg}")

print("\nDone.")
