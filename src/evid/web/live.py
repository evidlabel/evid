"""Live mode: notice changes made outside the GUI (an agent, the CLI, an editor).

A thread polls the data dir every ~1.5 s: for each set, a cheap signature per
document (the mtimes of the files that matter) plus the set list and the tag
registry. Differences become ``disk`` / ``sets_changed`` / ``tags_changed``
events for the page, which updates in place and merges into unsaved edits.

Writes the GUI makes itself are *touched* first, so the page can tell "you"
from "outside" (an agent cleaning up titles shows as outside).

When an outside change leaves a ``label.typ`` newer than its ``label.json``,
the labels are extracted again, so the Labels lists never go stale.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from evid.web.jobs import rebuild_labels

if TYPE_CHECKING:
    from evid.web.jobs import Events

logger = logging.getLogger(__name__)

WATCHED = ("info.yml", "evid_meta.yml", "annotations.yml", "label.typ", "label.json")
MINE_FOR = 6.0  # seconds a GUI write counts as "you"


def _mtime(p: Path) -> int | None:
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return None


def doc_signature(doc_dir: Path) -> tuple:
    """mtimes of the watched files, plus the folder (files added or removed)."""
    return (_mtime(doc_dir), *(_mtime(doc_dir / f) for f in WATCHED))


class DiskWatch:
    def __init__(self, data_dir: Path, events: Events, interval: float = 1.5) -> None:
        self.data_dir = Path(data_dir)
        self.events = events
        self.interval = interval
        self._lock = threading.Lock()
        self._mine: dict[
            tuple[str, str], float
        ] = {}  # (slug, uuid or "") -> when the GUI wrote
        self._docs: dict[str, dict[str, tuple]] = {}
        self._sets: tuple = ()
        self._tags: int | None = None
        self._fb: dict[str, int | None] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.snapshot_now()

    # the GUI's own writes ----------------------------------------------------

    def touch(self, slug: str, uuid: str = "") -> None:
        """Record that the GUI is about to change *uuid* in *slug* (or the set as a whole)."""
        with self._lock:
            self._mine[(slug, uuid)] = time.time()

    def _by(self, slug: str, uuid: str) -> str:
        now = time.time()
        with self._lock:
            t = max(self._mine.get((slug, uuid), 0.0), self._mine.get((slug, ""), 0.0))
        return "you" if now - t < MINE_FOR else "outside"

    # scanning ----------------------------------------------------------------

    def _scan_set(self, slug: str) -> dict[str, tuple]:
        docs = self.data_dir / "sets" / slug / "docs"
        try:
            return {
                d.name: doc_signature(d)
                for d in docs.iterdir()
                if d.is_dir() and (d / "info.yml").exists()
            }
        except OSError:
            return {}

    def _scan_sets(self) -> tuple:
        root = self.data_dir / "sets"
        try:
            return tuple(
                sorted(
                    (d.name, _mtime(d / "set.yml"))
                    for d in root.iterdir()
                    if d.is_dir()
                )
            )
        except OSError:
            return ()

    def snapshot_now(self) -> None:
        self._sets = self._scan_sets()
        self._docs = {slug: self._scan_set(slug) for slug, _ in self._sets}
        self._tags = _mtime(self.data_dir / "tags.yml")
        self._fb = {
            slug: _mtime(self.data_dir / "sets" / slug / "feedback.yml")
            for slug, _ in self._sets
        }

    def poll(self) -> None:
        """Compare with the last scan and report what changed (the thread calls this; tests too)."""
        sets = self._scan_sets()
        if sets != self._sets:
            self._sets = sets
            self.events.emit("sets_changed")
        tags = _mtime(self.data_dir / "tags.yml")
        if tags != self._tags:
            self._tags = tags
            self.events.emit("tags_changed")
        for slug, _ in sets:
            fb = _mtime(self.data_dir / "sets" / slug / "feedback.yml")
            if fb != self._fb.get(slug):  # requests to the agent asked or answered
                self._fb[slug] = fb
                self.events.emit("feedback", slug=slug, by=self._by(slug, "feedback"))
            new = self._scan_set(slug)
            old = self._docs.get(slug, {})
            if new == old:
                continue
            self._docs[slug] = new
            changed = []
            for uuid, sig in new.items():
                before = old.get(uuid)
                if before is None or before == sig:
                    continue
                files = [
                    f
                    for f, a, b in zip(("folder", *WATCHED), before, sig, strict=True)
                    if a != b
                ]
                changed.append(
                    {"uuid": uuid, "by": self._by(slug, uuid), "files": files}
                )
                self._maybe_extract(slug, uuid, sig)
            added = [{"uuid": u, "by": self._by(slug, u)} for u in new if u not in old]
            removed = [
                {"uuid": u, "by": self._by(slug, u)} for u in old if u not in new
            ]
            outside = sum(
                1 for c in (*changed, *added, *removed) if c["by"] == "outside"
            )
            if outside:
                logger.info(
                    "'%s': %d document(s) changed outside the app", slug, outside
                )
            self.events.emit(
                "disk", slug=slug, changed=changed, added=added, removed=removed
            )

    def _maybe_extract(self, slug: str, uuid: str, sig: tuple) -> None:
        """label.typ edited outside and newer than label.json: extract the labels again."""
        typ_m, json_m = (
            sig[1 + WATCHED.index("label.typ")],
            sig[1 + WATCHED.index("label.json")],
        )
        if (
            typ_m is None
            or (json_m is not None and json_m >= typ_m)
            or self._by(slug, uuid) == "you"
        ):
            return
        doc_dir = self.data_dir / "sets" / slug / "docs" / uuid
        self.touch(slug, uuid)
        rebuild_labels(self.events, doc_dir / "label.typ", slug, uuid)
        self._docs[slug][uuid] = doc_signature(
            doc_dir
        )  # our own rebuild is not a change

    # thread ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="evid-live", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.poll()
            except Exception:
                logger.exception("Live disk watch failed")
