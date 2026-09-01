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
        if not server.listen(name):
            _notify_existing(name)
            return None
        return cls(server, name)

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
            self.raise_requested.emit()
        sock.disconnectFromServer()


def _notify_existing(name: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(200):
        return False
    sock.write(b"raise\n")
    sock.waitForBytesWritten(500)
    sock.flush()
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(200)
    return True
