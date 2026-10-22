# fmt: off
"""The agent pane's terminals: shells on pseudo-terminals, shared by every connected page over WebSocket.

Taken from treedit (same author, MIT).

Standard library only (POSIX). The shell starts lazily on the first connection; with an agent
preset (e.g. "claude") the command is typed into the shell, so quitting the agent leaves you at
a prompt. Output is kept in a scrollback buffer and replayed when a page (re)connects.

Each page has its own writer thread, so a page that stops reading (a busy webview) can never
block the pty: the agent's writes would block behind it and the session would look hung.

A terminal may take a ``wrap`` hook: ``() -> (argv prefix, env)``, read at every start. evid uses
it for the sandbox (``evid.web.sandbox``); the workbench uses it for its case sandbox.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import signal
import socket
import struct
import subprocess
import termios
import threading
from collections import deque

SCROLLBACK = 256 * 1024
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
QUEUE_MAX = 8 * 1024 * 1024  # bytes one page may lag behind by; past it the page is dropped


# ---------- WebSocket (RFC 6455, just what a terminal needs) ----------
def ws_accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def ws_recv(rfile):
    """(opcode, payload) of the next client frame, reassembling fragments; None when the peer is gone."""
    try:
        return _ws_recv(rfile)
    except (OSError, struct.error):  # reset / closed tab
        return None


def _ws_recv(rfile):
    data, first_op = b"", None
    while True:
        head = rfile.read(2)
        if len(head) < 2:
            return None
        fin, op, masked, n = head[0] & 0x80, head[0] & 0x0F, head[1] & 0x80, head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", rfile.read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", rfile.read(8))[0]
        mask = rfile.read(4) if masked else b"\0\0\0\0"
        raw = rfile.read(n)
        if len(raw) < n:
            return None
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(raw)) if masked else raw
        if op >= 8:  # control frames may arrive between fragments
            return op, payload
        first_op = op if first_op is None else first_op
        data += payload
        if fin:
            return first_op, data


def ws_frame(op: int, payload: bytes) -> bytes:
    n = len(payload)
    if n < 126:
        head = struct.pack(">BB", 0x80 | op, n)
    elif n < 65536:
        head = struct.pack(">BBH", 0x80 | op, 126, n)
    else:
        head = struct.pack(">BBQ", 0x80 | op, 127, n)
    return head + payload


class Client:
    """One page's terminal socket: frames are queued and written by this client's own thread.

    The pty must never wait for a page. A webview that is busy (a big re-render, a reload, a
    suspended window) stops reading, and a synchronous send there fills the socket and blocks the
    pty reader - which blocks the agent's own writes, so the whole session looks hung. Past
    QUEUE_MAX the page is dropped instead; it reconnects and gets the scrollback."""

    def __init__(self, sock):
        self.sock = sock
        self.cond = threading.Condition()
        self.q: deque = deque()
        self.pending = 0
        self.closed = False
        self.thread = threading.Thread(target=self._write, name="term-write", daemon=True)
        self.thread.start()

    def send(self, op: int, payload: bytes) -> bool:
        with self.cond:
            if self.closed:
                return False
            self.q.append((op, payload))
            self.pending += len(payload)
            if self.pending > QUEUE_MAX:
                self._shut()
                return False
            self.cond.notify()
        return True

    def _shut(self) -> None:
        """Drop the queue and wake a writer stuck in sendall; the socket's read side ends too."""
        self.closed = True
        self.q.clear()
        self.pending = 0
        self.cond.notify()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def close(self) -> None:
        with self.cond:
            self.closed = True
            self.cond.notify()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _write(self) -> None:
        while True:
            with self.cond:
                while not self.q and not self.closed:
                    self.cond.wait()
                if not self.q:
                    return  # closed and drained, or closed by the page
                op, payload = self.q.popleft()
                self.pending -= len(payload)
            try:
                self.sock.sendall(ws_frame(op, payload))
            except OSError:
                self.close()
                return


# ---------- the shared terminal ----------
class Terminal:
    def __init__(self, cwd: str, env: dict, agent: str = "", wrap=None, name: str = "", on_change=None):
        self.cwd, self.env, self.agent = cwd, env, agent
        self.name = name  # the agent menu's row ("OpenCode · local"); the title instead of the command
        self.wrap = wrap  # () -> (argv prefix, env): the sandbox, read at every start
        self.on_change = on_change  # called when the session starts or ends
        self.sandboxed = False
        self.lock = threading.Lock()
        self.clients: set = set()
        self.buf = bytearray()
        self.proc = None
        self.master = None
        self.size = (24, 80)
        self.gen = 0  # session number; a finished old session must not report on a new one

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def label(self) -> str:
        return self.name or self.agent or os.path.basename(self.env.get("SHELL") or "sh")

    def start(self) -> None:
        with self.lock:
            if self.alive:
                return
            shell = self.env.get("SHELL") or "/bin/sh"
            master, slave = os.openpty()
            self._winsize(master)

            def ctty():  # runs in the child after setsid(): make the pty its controlling terminal
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            prefix, env = self.wrap() if self.wrap else ([], self.env)
            self.sandboxed = bool(prefix)
            self.proc = subprocess.Popen(
                [*prefix, shell, "-i"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=self.cwd,
                env=env,
                start_new_session=True,
                preexec_fn=ctty,
                close_fds=True,
            )
            os.close(slave)
            self.master = master
            self.gen += 1
            self.buf.clear()
            for c in list(self.clients):
                c.send(1, json.dumps({"t": "reset"}).encode())
            threading.Thread(target=self._pump, args=(master, self.gen), daemon=True).start()
            if self.agent:
                self.write((self.agent + "\r").encode())
        if self.on_change:
            self.on_change()

    def _winsize(self, fd: int) -> None:
        rows, cols = self.size
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _pump(self, master: int, gen: int) -> None:
        while True:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            self._broadcast(chunk)
        try:
            os.close(master)
        except OSError:
            pass
        if gen != self.gen:
            return
        self.master = None
        self._broadcast(b"\r\n\x1b[2m[session ended - Restart to start a new one]\x1b[0m\r\n")
        for c in list(self.clients):
            c.send(1, json.dumps({"t": "exit"}).encode())
        if self.on_change:
            self.on_change()

    def _broadcast(self, chunk: bytes) -> None:
        with self.lock:
            self.buf += chunk
            if len(self.buf) > SCROLLBACK:
                del self.buf[: len(self.buf) - SCROLLBACK]
            clients = list(self.clients)
        for c in clients:
            if not c.send(2, chunk):
                with self.lock:
                    self.clients.discard(c)

    def write(self, data: bytes) -> None:
        if self.master is not None:
            try:
                os.write(self.master, data)
            except OSError:
                pass

    def resize(self, rows: int, cols: int) -> None:
        self.size = (max(2, rows), max(10, cols))
        if self.master is not None:
            try:
                self._winsize(self.master)
            except OSError:
                pass

    def stop(self) -> None:
        if self.alive:
            try:
                os.killpg(self.proc.pid, signal.SIGHUP)
                self.proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                    self.proc.wait(timeout=5)  # reaped: else it still looks alive and restart starts nothing
                except (OSError, subprocess.TimeoutExpired):
                    pass

    def restart(self) -> None:
        self.gen += 1
        self.stop()
        self.start()

    def serve(self, sock, rfile) -> None:
        """Run one WebSocket connection: replay scrollback, then relay input and resizes."""
        client = Client(sock)
        with self.lock:
            backlog = bytes(self.buf)
            self.clients.add(client)
        client.send(1, json.dumps({"t": "hello", "label": self.label()}).encode())
        if backlog:
            client.send(2, backlog)
        if not self.alive:
            self.start()
        try:
            while True:
                msg = ws_recv(rfile)
                if msg is None:
                    break
                op, payload = msg
                if op == 8:
                    client.send(8, b"")
                    break
                if op == 9:
                    client.send(10, payload)
                    continue
                if op not in (1, 2):
                    continue
                try:
                    m = json.loads(payload)
                except ValueError:
                    continue
                if m.get("t") == "in":
                    self.write(str(m.get("d", "")).encode("utf-8", "surrogateescape"))
                elif m.get("t") == "resize":
                    self.resize(int(m.get("rows", 24)), int(m.get("cols", 80)))
                elif m.get("t") == "restart":
                    self.restart()
        finally:
            self.clients.discard(client)
            client.close()


# ---------- the sessions of the pane ----------
class Sessions:
    """The terminals of the agent pane, in the order they were added: each its own shell or agent preset
    on a pseudo-terminal, started in CWD with ENV. The first runs AGENT; more are added from the page."""

    def __init__(self, cwd: str, env: dict, agent: str | None = "", on_change=None, wrap=None):
        self.cwd, self.env, self.wrap = cwd, env, wrap
        self.on_change = on_change
        self.lock = threading.Lock()
        self.terms: dict = {}
        self.next = 1
        if agent is not None:  # None: start empty; terminals are added from the page
            self.add(agent)

    def add(self, agent: str = "", name: str = "") -> str:
        with self.lock:
            sid = str(self.next)
            self.next += 1
            self.terms[sid] = Terminal(self.cwd, self.env, agent.strip(), self.wrap, name.strip(), self.on_change)
        if self.on_change:
            self.on_change()
        return sid

    def get(self, sid: str):
        return self.terms.get(sid)

    def close(self, sid: str) -> bool:
        with self.lock:
            t = self.terms.pop(sid, None)
        if t is None:
            return False
        t.stop()
        for c in list(t.clients):  # tell its pages the pane is gone
            c.send(1, json.dumps({"t": "closed"}).encode())
            c.send(8, b"")
        if self.on_change:
            self.on_change()
        return True

    def list(self) -> list:
        return [
            {"id": sid, "label": t.label(), "agent": t.agent, "alive": t.alive, "sandboxed": t.sandboxed}
            for sid, t in list(self.terms.items())
        ]

    def stop(self) -> None:
        for t in list(self.terms.values()):
            t.stop()
