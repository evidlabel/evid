"""Live mode: notice changes made outside the GUI (an agent, the CLI, an editor).

A thread watches the data dir. For each set it keeps a cheap signature per
document (the mtimes of the files that matter) plus the set list and the tag
registry. Differences become ``disk`` / ``sets_changed`` / ``tags_changed``
events for the page, which updates in place and merges into unsaved edits.

The thread blocks in inotify and scans only after the kernel reports a
change. Scanning every document on a timer takes about a quarter of a second
once a set holds a few thousand documents, which is a steady slice of a core
while the window sits idle. If inotify cannot be set up, the thread polls
every ``interval`` seconds.

Writes the GUI makes itself are *touched* first, so the page can tell "you"
from "outside" (an agent cleaning up titles shows as outside).

An agent's ``evid label add`` shows up as a ``disk`` event on
``label/labels.json`` (or ``pass/`` for a quote pass). The page tells "you"
from "outside" by the touch the GUI makes before its own writes.
"""

from __future__ import annotations

import ctypes
import errno
import logging
import os
import select
import struct
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from evid.services.layout import find_set_dir, iter_set_dirs, read_slug

if TYPE_CHECKING:
    from evid.web.jobs import Events

logger = logging.getLogger(__name__)

# ``pass`` is the folder: a new or edited pass changes its mtime.
WATCHED = ("info.yml", "annotations.yml", "label/labels.json", "pass")
MINE_FOR = 6.0  # seconds a GUI write counts as "you"
_BUCKETS = ("anon", "plain", "sets")

# Linux inotify. The stdlib has no wrapper. Flag values are the kernel's.
_IN_MODIFY = 0x00000002
_IN_ATTRIB = 0x00000004
_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_Q_OVERFLOW = 0x00004000
_IN_IGNORED = 0x00008000
_IN_ONLYDIR = 0x01000000
_IN_ISDIR = 0x40000000
_IN_CLOEXEC = 0x00080000
_IN_NONBLOCK = 0x00000800
_IN_WATCH = (
    _IN_MODIFY
    | _IN_ATTRIB
    | _IN_CLOSE_WRITE
    | _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
    | _IN_ONLYDIR
)
_IN_EVENT = struct.Struct("iIII")  # wd, mask, cookie, name length
_LIBC = None


def _mtime(p: Path) -> int | None:
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return None


def doc_signature(doc_dir: Path) -> tuple:
    """mtimes of the watched files, plus the folder (files added or removed)."""
    return (_mtime(doc_dir), *(_mtime(doc_dir / f) for f in WATCHED))


def _is_watch_dir(data_dir: Path, path: Path) -> bool:
    """True for the set tree the scanner reads, and not for ``vecdb`` or files.

    ``anon`` / ``plain`` / ``sets``, each set directory, its ``docs``, each
    document, and that document's ``label`` and ``pass`` folders.
    """
    try:
        parts = path.relative_to(data_dir).parts
    except ValueError:
        return False
    if not parts or parts[0] not in _BUCKETS:
        return False
    if len(parts) <= 2:
        return True
    if parts[2] != "docs":
        return False
    if len(parts) == 3:
        return True
    if len(parts) == 4:
        return True
    return len(parts) == 5 and parts[4] in ("label", "pass")


def _libc():
    global _LIBC
    if _LIBC is None:
        lib = ctypes.CDLL(None, use_errno=True)
        lib.inotify_init1.argtypes = (ctypes.c_int,)
        lib.inotify_init1.restype = ctypes.c_int
        lib.inotify_add_watch.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint32,
        )
        lib.inotify_add_watch.restype = ctypes.c_int
        _LIBC = lib
    return _LIBC


def _inotify_fd() -> int | None:
    """A non-blocking inotify fd, or None when this kernel has no inotify."""
    try:
        fd = _libc().inotify_init1(_IN_CLOEXEC | _IN_NONBLOCK)
    except (AttributeError, OSError):
        return None
    if fd < 0:
        return None
    return fd


class DiskWatch:
    def __init__(
        self,
        data_dir: Path,
        events: Events,
        interval: float = 1.5,
        *,
        root_id: str = "",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.events = events
        self.interval = interval
        self.root_id = root_id  # set on an extra trunk; empty on the primary dir
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
        self._ready = threading.Event()
        self._wake_r: int | None = None
        self._wake_w: int | None = None
        self._wd_path: dict[int, Path] = {}
        self._in_buf = b""
        self._nospace = False
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

    def _set_path(self, slug: str) -> Path | None:
        return find_set_dir(self.data_dir, slug)

    def _scan_set(self, slug: str) -> dict[str, tuple]:
        found = self._set_path(slug)
        if found is None:
            return {}
        docs = found / "docs"
        try:
            return {
                d.name: doc_signature(d)
                for d in docs.iterdir()
                if d.is_dir() and (d / "info.yml").exists()
            }
        except OSError:
            return {}

    def _scan_sets(self) -> tuple:
        rows = []
        for set_dir in iter_set_dirs(self.data_dir):
            slug = read_slug(set_dir)
            if slug:
                rows.append((slug, _mtime(set_dir / "set.yml")))
        return tuple(rows)

    def _feedback_mtime(self, slug: str) -> int | None:
        found = self._set_path(slug)
        if found is None:
            return None
        return _mtime(found / "feedback.yml")

    def snapshot_now(self) -> None:
        self._sets = self._scan_sets()
        self._docs = {slug: self._scan_set(slug) for slug, _ in self._sets}
        self._tags = _mtime(self.data_dir / "tags.yml")
        self._fb = {slug: self._feedback_mtime(slug) for slug, _ in self._sets}

    def _emit(self, kind: str, **fields) -> None:
        """Send an event. An extra trunk names itself so the page can tell trunks apart."""
        if self.root_id:
            fields["root"] = self.root_id
        self.events.emit(kind, **fields)

    def poll(self) -> None:
        """Compare with the last scan and report what changed (the thread calls this; tests too)."""
        sets = self._scan_sets()
        if sets != self._sets:
            self._sets = sets
            self._emit("sets_changed")
        tags = _mtime(self.data_dir / "tags.yml")
        if tags != self._tags:
            self._tags = tags
            self._emit("tags_changed")
        for slug, _ in sets:
            fb = self._feedback_mtime(slug)
            if fb != self._fb.get(slug):  # requests to the agent asked or answered
                self._fb[slug] = fb
                self._emit("feedback", slug=slug, by=self._by(slug, "feedback"))
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
            self._emit("disk", slug=slug, changed=changed, added=added, removed=removed)

    # thread ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._wake_r, self._wake_w = os.pipe()
            os.set_blocking(self._wake_r, False)
            os.set_blocking(self._wake_w, False)
            self._thread = threading.Thread(
                target=self._run, name="evid-live", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        w = self._wake_w
        if w is not None:
            try:
                os.write(w, b"x")
            except OSError:
                pass

    def _run(self) -> None:
        try:
            self._run_inotify()
        except Exception:
            logger.exception(
                "Live disk watch could not use inotify; polling every %.1f s",
                self.interval,
            )
            self._ready.set()
            if not self._stop.is_set():
                self._run_poll()
        finally:
            self._close_wake()

    def _run_poll(self) -> None:
        while not self._stop.wait(self.interval):
            self._safe_poll()

    def _safe_poll(self) -> None:
        try:
            self.poll()
        except Exception:
            logger.exception("Live disk watch failed")

    def _close_wake(self) -> None:
        for attr in ("_wake_r", "_wake_w"):
            fd = getattr(self, attr)
            if fd is None:
                continue
            setattr(self, attr, None)
            try:
                os.close(fd)
            except OSError:
                pass

    def _run_inotify(self) -> None:
        fd = _inotify_fd()
        if fd is None:
            raise OSError("inotify_init1 failed")
        try:
            self._arm(fd)
            logger.debug(
                "inotify watching %d directories under %s",
                len(self._wd_path),
                self.data_dir,
            )
            self._ready.set()
            poller = select.poll()
            poller.register(fd, select.POLLIN)
            if self._wake_r is not None:
                poller.register(self._wake_r, select.POLLIN)
            pending = False
            while not self._stop.is_set():
                ready = poller.poll(200 if pending else None)
                if self._stop.is_set():
                    break
                woke = False
                for nfd, _ev in ready:
                    if nfd == fd:
                        if self._drain_inotify(fd):
                            pending = True
                            woke = True
                    else:
                        self._drain_wake()
                if pending and not woke:
                    pending = False
                    self._safe_poll()
        finally:
            os.close(fd)
            self._wd_path.clear()
            self._in_buf = b""

    def _arm(self, fd: int) -> None:
        self._follow(fd, self.data_dir, root=True)
        if self._nospace:
            raise OSError(errno.ENOSPC, "inotify watch limit reached")

    def _follow(self, fd: int, path: Path, *, root: bool = False) -> None:
        """Watch *path* and the set-tree directories already under it."""
        if not root and not _is_watch_dir(self.data_dir, path):
            return
        if not self._add(fd, path):
            return
        try:
            children = [p for p in path.iterdir() if p.is_dir()]
        except OSError:
            return
        for child in children:
            self._follow(fd, child)

    def _add(self, fd: int, path: Path) -> bool:
        if not path.is_dir():
            return False
        wd = _libc().inotify_add_watch(fd, os.fsencode(path), _IN_WATCH)
        if wd < 0:
            err = ctypes.get_errno()
            if err == errno.ENOSPC:
                self._nospace = True
            elif err not in (errno.ENOENT, errno.ENOTDIR):
                logger.debug("inotify_add_watch %s failed: errno %s", path, err)
            return False
        self._wd_path[wd] = path
        return True

    def _drain_wake(self) -> None:
        fd = self._wake_r
        if fd is None:
            return
        while True:
            try:
                if not os.read(fd, 64):
                    return
            except BlockingIOError:
                return
            except OSError:
                return

    def _drain_inotify(self, fd: int) -> bool:
        """Read queued events. True when a scan is due."""
        scan = False
        while True:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            self._in_buf += chunk
            for mask, path, isdir in self._pop_events():
                scan = True
                if mask & _IN_Q_OVERFLOW:
                    self._arm(fd)
                elif isdir and path is not None and mask & (_IN_CREATE | _IN_MOVED_TO):
                    self._follow(fd, path)
                if self._nospace:
                    raise OSError(errno.ENOSPC, "inotify watch limit reached")
        return scan

    def _pop_events(self):
        data = self._in_buf
        i = 0
        n = len(data)
        out = []
        header = _IN_EVENT.size
        while i + header <= n:
            wd, mask, _cookie, length = _IN_EVENT.unpack_from(data, i)
            end = i + header + length
            if end > n:
                break
            raw = data[i + header : end].split(b"\0", 1)[0]
            i = end
            if mask & _IN_IGNORED:
                self._wd_path.pop(wd, None)
            parent = self._wd_path.get(wd)
            name = os.fsdecode(raw) if raw else ""
            path = parent / name if parent is not None and name else parent
            out.append((mask, path, bool(mask & _IN_ISDIR)))
        self._in_buf = data[i:]
        return out
