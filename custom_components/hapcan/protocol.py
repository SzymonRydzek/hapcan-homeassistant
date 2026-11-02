"""HAPCAN frame encoding and decoding.

Pure Python, no Home Assistant imports, so it can be unit tested on its own.

A frame exchanged with the HAPCAN Ethernet interface is 15 bytes:

    0xAA | type_hi | type_lo+flags | node | group | D0..D7 | checksum | 0xA5

The checksum is the low byte of the sum of every byte between the start and
the checksum.
"""

from __future__ import annotations

from dataclasses import dataclass

FRAME_LEN = 15
START = 0xAA
STOP = 0xA5

# Frame identifiers as the first two bytes after START, rendered as upper hex.
RELAY_FRAME_ID = "3020"  # relay status change broadcast
RELAY_FRAME_RESP_ID = "3021"  # relay status as a response to a request
BUTTON_FRAME_ID = "3010"
BLIND_FRAME_ID = "3070"  # blind controller status change broadcast
BLIND_FRAME_RESP_ID = "3071"  # blind controller status as a response to a request

# Request frame types sent from the computer.
STATUS_REQUEST = (0x10, 0x90)
CONTROL_REQUEST = (0x10, 0xA0)

# Sender id used for frames sent from Home Assistant. Any value works.
TRANSMITTER_ID = (0x12, 0x23)

# Relay instructions (D0 of a control frame).
RELAY_OFF = 0x00
RELAY_ON = 0x01
RELAY_TOGGLE = 0x02

# Blind controller (UNIV 3.7.0.x) instructions (D0 of a control frame).
BLIND_STOP = 0x00
BLIND_UP = 0x03  # also reverses a blind running down, after 1 s
BLIND_DOWN = 0x04  # also reverses a blind running up, after 1 s

# Blind controller MOVE byte.
BLIND_MOVE_STOPPED = 0x00
BLIND_MOVE_DOWN = 0x01
BLIND_MOVE_UP = 0x02


def checksum(data: bytes | list[int]) -> int:
    """Low byte of the sum of ``data``."""
    return sum(data) & 0xFF


def build_frame(frame_type: tuple[int, int], payload: list[int]) -> bytes:
    """Build a complete frame from its type and 8 data bytes."""
    if len(payload) != 8:
        raise ValueError(f"payload must have 8 bytes, got {len(payload)}")
    body = [*frame_type, *TRANSMITTER_ID, *payload]
    return bytes([START, *body, checksum(body), STOP])


def relay_instruction(command: int, channel: int, node: int, group: int) -> list[int]:
    """Instruction bytes addressing one relay channel (1-6) of a module."""
    if not 1 <= channel <= 8:
        raise ValueError(f"channel out of range: {channel}")
    return [command, 1 << (channel - 1), node, group, 0x00, 0x00, 0x00, 0x00]


def relay_control_frame(command: int, channel: int, node: int, group: int) -> bytes:
    """Frame switching a relay channel on, off or toggling it."""
    return build_frame(CONTROL_REQUEST, relay_instruction(command, channel, node, group))


def blind_control_frame(instruction: int, channel: int, node: int, group: int) -> bytes:
    """Frame running one blind (channel 1-3) of a blind controller.

    D0 instruction, D1 channel bit mask, D2/D3 module, D4 delay (0 = now).
    """
    if not 1 <= channel <= 3:
        raise ValueError(f"blind channel out of range: {channel}")
    return build_frame(
        CONTROL_REQUEST, [instruction, 1 << (channel - 1), node, group, 0x00, 0x00, 0x00, 0x00]
    )


def status_request_frame(node: int, group: int) -> bytes:
    """Frame asking a module to report the state of all its channels.

    Byte layout kept identical to the original integration, which the
    installed modules are known to answer.
    """
    return build_frame(STATUS_REQUEST, [0x00, 0x01, node, group, 0x00, 0x00, 0x00, 0x00])


@dataclass(frozen=True)
class RelayStatus:
    """A relay channel state reported on the bus."""

    node: int
    group: int
    channel: int
    is_on: bool
    instr1: int
    instr2: int
    timer: int


@dataclass(frozen=True)
class BlindStatus:
    """A blind controller channel state reported on the bus."""

    node: int
    group: int
    channel: int
    raw_position: int  # 0x00 fully open ... 0xFF fully closed
    move: int  # BLIND_MOVE_*

    @property
    def position(self) -> int:
        """Position in Home Assistant terms: 100 open, 0 closed."""
        return raw_to_position(self.raw_position)


def raw_to_position(raw: int) -> int:
    """Blind controller position byte to 0-100 (100 = open)."""
    return round((255 - raw) * 100 / 255)


def frame_id(frame: bytes) -> str:
    """Identifier of a frame, e.g. ``3020``."""
    return f"{frame[1]:X}{frame[2]:X}"


def validate(frame: bytes) -> str | None:
    """Return None if ``frame`` is valid, otherwise the reason it is not."""
    if len(frame) != FRAME_LEN:
        return f"wrong length {len(frame)}"
    if frame[0] != START or frame[-1] != STOP:
        return f"bad start/stop bytes 0x{frame[0]:02x}/0x{frame[-1]:02x}"
    expected = checksum(frame[1:-2])
    if expected != frame[-2]:
        return f"bad checksum 0x{frame[-2]:02x}, calculated 0x{expected:02x}"
    return None


def parse_relay_status(frame: bytes) -> RelayStatus:
    """Decode a relay status frame (``3020`` or ``3021``)."""
    return RelayStatus(
        node=frame[3],
        group=frame[4],
        channel=frame[7],
        is_on=frame[8] == 0xFF,
        instr1=frame[10],
        instr2=frame[11],
        timer=frame[12],
    )


def parse_blind_status(frame: bytes) -> BlindStatus:
    """Decode a blind controller status frame (``3070`` or ``3071``)."""
    return BlindStatus(
        node=frame[3],
        group=frame[4],
        channel=frame[7],
        raw_position=frame[8],
        move=frame[9],
    )


class FrameBuffer:
    """Reassemble frames from a byte stream, resynchronising on garbage."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.dropped = 0

    def feed(self, data: bytes) -> list[bytes]:
        """Add received bytes and return every complete, valid frame."""
        self._buf.extend(data)
        frames: list[bytes] = []
        while True:
            start = self._buf.find(START)
            if start < 0:
                self.dropped += len(self._buf)
                self._buf.clear()
                break
            if start:
                self.dropped += start
                del self._buf[:start]
            if len(self._buf) < FRAME_LEN:
                break
            candidate = bytes(self._buf[:FRAME_LEN])
            if validate(candidate) is None:
                frames.append(candidate)
                del self._buf[:FRAME_LEN]
            else:
                # Not a real frame start; skip this byte and search again.
                self.dropped += 1
                del self._buf[0]
        return frames
