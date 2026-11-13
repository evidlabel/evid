"""Run the TUI directly: ``python -m evid.tui [--db DIR] [--dataset SLUG]``."""

import sys

from evid.tui import app


def main() -> None:
    db = None
    dataset = None
    args = sys.argv[1:]
    if "--db" in args:
        i = args.index("--db")
        if i + 1 < len(args):
            db = args[i + 1]
    if "--dataset" in args:
        i = args.index("--dataset")
        if i + 1 < len(args):
            dataset = args[i + 1]
    sys.exit(app.run(db=db, dataset=dataset))


if __name__ == "__main__":
    main()
