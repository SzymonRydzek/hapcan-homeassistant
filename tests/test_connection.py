import asyncio

import pytest

from hapcan import connection as conn_mod
from hapcan import protocol


def _relay_frame(channel, on):
    body = [0x30, 0x20, 0x0C, 0xF4, 0xFF, 0xFF, channel, 0xFF if on else 0x00, 0xFF, 0, 0, 0]
    return bytes([0xAA, *body, sum(body) & 0xFF, 0xA5])


def test_reconnects_and_requests_status(monkeypatch):
    monkeypatch.setattr(conn_mod, "RECONNECT_DELAY", 0.1)
    monkeypatch.setattr(conn_mod, "SEND_GAP", 0)

    async def scenario():
        connections = []
        received = []

        async def handler(reader, writer):
            connections.append(writer)
            data = await reader.readexactly(protocol.FRAME_LEN)
            received.append(data)
            frame = _relay_frame(3, True)
            writer.write(frame[:5])
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(frame[5:])
            await writer.drain()
            await asyncio.sleep(0.1)
            if len(connections) == 1:
                writer.close()  # drop the first connection
            else:
                await asyncio.sleep(1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        statuses, changes = [], []
        conn = conn_mod.HapcanConnection(
            "127.0.0.1", port, statuses.append, changes.append, lambda: {(0x0C, 0xF4)}
        )
        task = asyncio.create_task(conn.run())
        for _ in range(100):
            if len(statuses) >= 2:
                break
            await asyncio.sleep(0.05)
        await conn.close()
        task.cancel()
        server.close()
        return received, statuses, changes

    received, statuses, changes = asyncio.run(scenario())
    assert received[0] == protocol.status_request_frame(0x0C, 0xF4)
    assert len(statuses) >= 2 and statuses[0].channel == 3 and statuses[0].is_on
    assert changes[:3] == [True, False, True]


def test_send_when_disconnected_raises():
    conn = conn_mod.HapcanConnection("127.0.0.1", 1, lambda s: None, lambda c: None, set)
    with pytest.raises(ConnectionError):
        asyncio.run(conn.send(b"x"))


def test_blind_frames_reach_blind_callback():
    body = [0x30, 0x70, 0x0A, 0x20, 0xFF, 0xFF, 1, 0x00, 0x02, 0xFF, 0xFF, 0x00]
    frame = bytes([0xAA, *body, sum(body) & 0xFF, 0xA5])
    relays, blinds = [], []
    conn = conn_mod.HapcanConnection(
        "127.0.0.1", 1, relays.append, lambda c: None, set, on_blind_status=blinds.append
    )
    conn._dispatch(frame)
    assert relays == [] and blinds[0].move == protocol.BLIND_MOVE_UP and blinds[0].position == 100
