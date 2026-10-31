from hapcan import protocol


def _relay_frame(node, group, channel, on):
    body = [0x30, 0x20, node, group, 0xFF, 0xFF, channel, 0xFF if on else 0x00, 0xFF, 0x00, 0x00, 0x00]
    return bytes([0xAA, *body, sum(body) & 0xFF, 0xA5])


def test_control_frame_matches_original_layout():
    # Same bytes the original integration sent for "turn on channel 3 of 0x0c/0xF4".
    frame = protocol.relay_control_frame(protocol.RELAY_ON, 3, 0x0C, 0xF4)
    body = [0x10, 0xA0, 0x12, 0x23, 0x01, 0x04, 0x0C, 0xF4, 0, 0, 0, 0]
    assert frame == bytes([0xAA, *body, sum(body) & 0xFF, 0xA5])
    assert len(frame) == protocol.FRAME_LEN
    assert protocol.validate(frame) is None


def test_status_request_frame_is_valid():
    frame = protocol.status_request_frame(0x0C, 0x8A)
    assert frame[1:3] == bytes([0x10, 0x90])
    assert frame[7:9] == bytes([0x0C, 0x8A])
    assert protocol.validate(frame) is None


def test_validate_rejects_bad_frames():
    good = _relay_frame(0x0C, 0xF4, 2, True)
    assert protocol.validate(good) is None
    assert "checksum" in protocol.validate(good[:-2] + bytes([good[-2] ^ 1]) + good[-1:])
    # Start byte right but stop byte wrong must be rejected (the old check let it through).
    assert "start/stop" in protocol.validate(good[:-1] + b"\x00")
    assert "length" in protocol.validate(good[:-1])


def test_parse_relay_status():
    status = protocol.parse_relay_status(_relay_frame(0x0C, 0xF4, 2, True))
    assert (status.node, status.group, status.channel, status.is_on) == (0x0C, 0xF4, 2, True)
    assert protocol.frame_id(_relay_frame(0x0C, 0xF4, 2, True)) == protocol.RELAY_FRAME_ID


def test_frame_buffer_split_and_garbage():
    a = _relay_frame(0x0C, 0xF4, 1, True)
    b = _relay_frame(0x0C, 0xF3, 5, False)
    buf = protocol.FrameBuffer()
    assert buf.feed(b"\x00\x13" + a[:7]) == []
    assert buf.feed(a[7:] + b[:3]) == [a]
    assert buf.feed(b[3:]) == [b]
    assert buf.dropped == 2


def test_frame_buffer_resyncs_after_false_start():
    a = _relay_frame(0x0C, 0xF4, 1, True)
    buf = protocol.FrameBuffer()
    # A stray 0xAA before a real frame must not swallow it.
    assert buf.feed(b"\xaa\x01" + a) == [a]
