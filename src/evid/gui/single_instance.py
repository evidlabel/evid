"""One evid GUI process at a time; a second launch asks the first to raise."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_DEFAULT_NAME = "evid-gui"


class GuiInstance(QObject):
    raise_requested = Signal()

    def __init__(self, server: QLocalServer, name: str) -> None:
        super().__init__()
        self._server = server
        self._name = name
        server.newConnection.connect(self._on_connection)

    @classmethod
    def acquire(cls, name: str = _DEFAULT_NAME) -> GuiInstance | None:
        """Listen as the primary instance, or tell the existing one to raise.

        Returns the primary handle, or None if this process should exit.
        """
        if _notify_existing(name):
            return None
        QLocalServer.removeServer(name)
        server = QLocalServer()
        if server.listen(name):
            return cls(server, name)
        # Stale socket: unlinked but a stopped peer may still hold the bind.
        if _notify_existing(name):
            return None
        QLocalServer.removeServer(name)
        if server.listen(name):
            return cls(server, name)
        return None

    def release(self) -> None:
        self._server.close()
        QLocalServer.removeServer(self._name)

    def _on_connection(self) -> None:
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(lambda s=sock: self._read(s))
        if sock.bytesAvailable():
            self._read(sock)

    def _read(self, sock: QLocalSocket) -> None:
        data = bytes(sock.readAll())
        if b"raise" in data:
            sock.write(b"ok\n")
            sock.waitForBytesWritten(200)
            sock.flush()
            self.raise_requested.emit()
        sock.disconnectFromServer()


def _notify_existing(name: str) -> bool:
    """Tell a live primary to raise. False if nobody acks (stale/stopped)."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(200):
        return False
    sock.write(b"raise\n")
    if not sock.waitForBytesWritten(500):
        sock.disconnectFromServer()
        return False
    sock.flush()
    if not sock.waitForReadyRead(400):
        sock.disconnectFromServer()
        return False
    reply = bytes(sock.readAll())
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(200)
    return b"ok" in reply
