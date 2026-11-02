"""Blind controller (UNIV 3.7.0.x) frames and stop logic, per the firmware note."""

import pytest

from hapcan import protocol
from hapcan.blind_model import DOWN, UP, controller_should_stop


def _blind_frame(channel, raw, move, response=False):
    body = [0x30, 0x71 if response else 0x70, 0x0A, 0x20, 0xFF, 0xFF, channel, raw, move, 0xFF, 0xFF, 0x00]
    return bytes([0xAA, *body, sum(body) & 0xFF, 0xA5])


def test_control_frame_layout():
    # DIRECT CONTROL 0x10A: D0 INSTR1, D1 channel mask, D2 node, D3 group, D4 timer.
    frame = protocol.blind_control_frame(protocol.BLIND_DOWN, 3, 0x0A, 0x20)
    assert frame[1:3] == bytes([0x10, 0xA0])
    assert frame[5:10] == bytes([0x04, 0x04, 0x0A, 0x20, 0x00])
    assert protocol.validate(frame) is None


def test_control_frame_rejects_channel_4():
    with pytest.raises(ValueError):
        protocol.blind_control_frame(protocol.BLIND_UP, 4, 1, 1)


@pytest.mark.parametrize("response", [False, True])
def test_status_frame_parsing(response):
    frame = _blind_frame(2, 0x80, protocol.BLIND_MOVE_DOWN, response)
    assert protocol.validate(frame) is None
    expected = protocol.BLIND_FRAME_RESP_ID if response else protocol.BLIND_FRAME_ID
    assert protocol.frame_id(frame) == expected
    status = protocol.parse_blind_status(frame)
    assert (status.node, status.group, status.channel) == (0x0A, 0x20, 2)
    assert status.move == protocol.BLIND_MOVE_DOWN
    assert status.position == 50  # 0x80 of 0xFF closed -> about half open


def test_position_scale():
    # 0x00 is fully open (HA 100), 0xFF fully closed (HA 0).
    assert protocol.raw_to_position(0x00) == 100
    assert protocol.raw_to_position(0xFF) == 0


def test_should_stop_accounts_for_step():
    # Moving up towards 60, 10 % per poll: stop once within half a step.
    assert not controller_should_stop(UP, 50, 60, 10)
    assert controller_should_stop(UP, 56, 60, 10)
    assert controller_should_stop(DOWN, 33, 30, 10)
    assert not controller_should_stop(DOWN, 40, 30, 10)
    # Overshoot also stops.
    assert controller_should_stop(UP, 65, 60, 0)
