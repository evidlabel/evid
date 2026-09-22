"""One evid GUI process at a time; a second launch asks the first to raise."""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
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
            sock.flush()
            self.raise_requested.emit()
        # waitForBytesWritten() here nests another loop in the client's
        # thread and can drop the ack. The peer reads "ok" and disconnects.
        sock.disconnectFromServer()


def _notify_existing(name: str) -> bool:
    """Tell a live primary to raise. False if nobody acks (stale/stopped).

    Pump a real event loop. ``QLocalSocket.waitFor*`` does not deliver
    ``QLocalServer.newConnection`` when both sockets share the test thread,
    so the primary never acks and ``acquire`` steals a live lock.
    """
    sock = QLocalSocket()
    loop = QEventLoop()
    ack = False
    done = False

    def finish() -> None:
        nonlocal ack, done
        if done:
            return
        done = True
        if sock.isReadable() and b"ok" in bytes(sock.readAll()):
            ack = True
        if loop.isRunning():
            loop.quit()

    def on_connected() -> None:
        sock.write(b"raise\n")
        sock.flush()

    sock.connected.connect(on_connected)
    sock.readyRead.connect(finish)
    sock.errorOccurred.connect(lambda _err: finish())
    QTimer.singleShot(800, finish)
    sock.connectToServer(name)
    if not ack and sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        loop.exec()
    done = True
    sock.disconnectFromServer()
    return ack
