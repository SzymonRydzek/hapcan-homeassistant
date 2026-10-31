import pytest

from hapcan.blind_model import DOWN, IDLE, UP, BlindModel
from hapcan.const import STOP_NONE, STOP_OPPOSITE, STOP_SAME


def test_without_travel_times_position_jumps_to_end():
    m = BlindModel()
    assert m.position(0) is None and m.is_closed(0) is None
    m.start(DOWN, 0)
    assert m.is_closed(0) is True
    m.start(UP, 1)
    assert m.is_closed(1) is False
    assert m.direction == IDLE


def test_travel_and_end_stop():
    m = BlindModel(20, 10, position=0)
    m.start(UP, 100)
    assert m.position(110) == pytest.approx(50)
    assert m.tick(110) is True
    assert m.tick(121) is False
    assert m.position(121) == 100 and m.direction == IDLE
    m.start(DOWN, 200)
    assert m.position(205) == pytest.approx(50)


def test_unknown_start_assumes_far_end():
    m = BlindModel(20, 20)
    m.start(DOWN, 0)
    assert m.position(10) == pytest.approx(50)


@pytest.mark.parametrize(
    ("method", "second", "stops"),
    [
        (STOP_OPPOSITE, DOWN, True),
        (STOP_OPPOSITE, UP, False),
        (STOP_SAME, UP, True),
        (STOP_SAME, DOWN, False),
        (STOP_NONE, DOWN, False),
    ],
)
def test_wall_button_pulse_semantics(method, second, stops):
    m = BlindModel(20, 20, method, position=0)
    m.handle_pulse(UP, 0)
    assert m.direction == UP
    m.handle_pulse(second, 5)
    if stops:
        assert m.direction == IDLE
        assert m.position(5) == pytest.approx(25)
    else:
        assert m.direction != IDLE


def test_time_to_target():
    m = BlindModel(20, 10, STOP_OPPOSITE, position=50)
    assert m.time_to(75, 0) == (UP, pytest.approx(5))
    assert m.time_to(0, 0) == (DOWN, pytest.approx(5))
    assert m.time_to(50, 0) == (IDLE, 0.0)
