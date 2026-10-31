"""Connection to the HAPCAN Ethernet interface.

Keeps one TCP connection open, reconnects when it drops and hands decoded
relay frames to a callback. No Home Assistant imports.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
import logging
import socket

from . import protocol

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 10  # seconds
CONNECT_TIMEOUT = 10
# Gap between frames sent in a burst, so the interface is not flooded.
SEND_GAP = 0.05


class HapcanConnection:
    """TCP link to the HAPCAN Ethernet interface."""

    def __init__(
        self,
        host: str,
        port: int,
        on_relay_status: Callable[[protocol.RelayStatus], None],
        on_connection_change: Callable[[bool], None],
        modules: Callable[[], Iterable[tuple[int, int]]],
    ) -> None:
        self.host = host
        self.port = port
        self._on_relay_status = on_relay_status
        self._on_connection_change = on_connection_change
        self._modules = modules
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._send_lock = asyncio.Lock()
        self._closing = False
        self.connected = False

    async def run(self) -> None:
        """Connect, read frames and reconnect until ``close`` is called."""
        while not self._closing:
            if not await self._connect():
                await asyncio.sleep(RECONNECT_DELAY)
                continue
            try:
                await self.request_all_status()
                await self._read_loop()
            except asyncio.CancelledError:
                raise
            except (OSError, ConnectionError) as err:
                _LOGGER.debug("HAPCAN connection error: %s", err)
            except Exception:  # noqa: BLE001 - keep the loop alive whatever happens
                _LOGGER.exception("Unexpected error on the HAPCAN connection")
            finally:
                await self._disconnect()
            if not self._closing:
                _LOGGER.warning(
                    "Connection to HAPCAN %s:%s lost, reconnecting in %ss",
                    self.host,
                    self.port,
                    RECONNECT_DELAY,
                )
                await asyncio.sleep(RECONNECT_DELAY)

    async def close(self) -> None:
        """Stop the connection loop and close the socket."""
        self._closing = True
        await self._disconnect()

    async def _connect(self) -> bool:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as err:
            _LOGGER.warning(
                "Cannot connect to HAPCAN %s:%s: %s", self.host, self.port, err
            )
            return False
        _enable_keepalive(self._writer)
        _LOGGER.info("Connected to HAPCAN %s:%s", self.host, self.port)
        self._set_connected(True)
        return True

    async def _disconnect(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
        self._set_connected(False)

    def _set_connected(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            self._on_connection_change(connected)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        buffer = protocol.FrameBuffer()
        while not self._closing:
            data = await self._reader.read(256)
            if not data:
                return  # connection closed by the interface
            for frame in buffer.feed(data):
                self._dispatch(frame)
            if buffer.dropped:
                _LOGGER.debug("Dropped %d stray bytes", buffer.dropped)
                buffer.dropped = 0

    def _dispatch(self, frame: bytes) -> None:
        fid = protocol.frame_id(frame)
        if fid in (protocol.RELAY_FRAME_ID, protocol.RELAY_FRAME_RESP_ID):
            status = protocol.parse_relay_status(frame)
            _LOGGER.debug("Relay status %s", status)
            self._on_relay_status(status)

    async def send(self, frame: bytes) -> None:
        """Send one frame; raise ConnectionError when not connected."""
        async with self._send_lock:
            if self._writer is None or not self.connected:
                raise ConnectionError("HAPCAN interface is not connected")
            _LOGGER.debug("Sending %s", frame.hex(" "))
            self._writer.write(frame)
            await self._writer.drain()
            await asyncio.sleep(SEND_GAP)

    async def request_all_status(self) -> None:
        """Ask every configured relay module for the state of its channels."""
        for node, group in sorted(set(self._modules())):
            await self.send(protocol.status_request_frame(node, group))


def _enable_keepalive(writer: asyncio.StreamWriter) -> None:
    """Detect a dead link even when the bus is quiet."""
    sock: socket.socket | None = writer.get_extra_info("socket")
    if sock is None:
        return
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for opt, value in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
        if hasattr(socket, opt):
            sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), value)
