"""Time-based position model for blinds driven by up/down relay pulses.

Pure Python, no Home Assistant imports. Positions follow Home Assistant's
convention: 100 is fully open, 0 is fully closed.
"""

from __future__ import annotations

from .const import STOP_NONE, STOP_OPPOSITE, STOP_SAME

UP = 1
DOWN = -1
IDLE = 0


class BlindModel:
    """Tracks where a blind is, based on which pulses were sent and when."""

    def __init__(
        self,
        travel_up: float | None = None,
        travel_down: float | None = None,
        stop_method: str = STOP_NONE,
        position: float | None = None,
    ) -> None:
        self.travel_up = travel_up
        self.travel_down = travel_down
        self.stop_method = stop_method
        self._position = position
        self.direction = IDLE
        self._start_time = 0.0
        self._start_pos = 0.0

    @property
    def has_travel_times(self) -> bool:
        return bool(self.travel_up) and bool(self.travel_down)

    @property
    def can_stop(self) -> bool:
        return self.stop_method in (STOP_OPPOSITE, STOP_SAME)

    def position(self, now: float) -> float | None:
        """Current position, or None while it is unknown."""
        if self.direction == IDLE or not self.has_travel_times:
            return self._position
        travel = self.travel_up if self.direction == UP else self.travel_down
        moved = (now - self._start_time) / travel * 100
        pos = self._start_pos + moved * self.direction
        return max(0.0, min(100.0, pos))

    def is_closed(self, now: float) -> bool | None:
        pos = self.position(now)
        return None if pos is None else pos <= 0

    def start(self, direction: int, now: float) -> None:
        """A movement in ``direction`` began at ``now``."""
        if not self.has_travel_times:
            # No timing: assume it simply ends at the end stop.
            self.direction = IDLE
            self._position = 100.0 if direction == UP else 0.0
            return
        current = self.position(now)
        if current is None:
            # Unknown start: assume the far end, so the blind is in sync
            # once this movement completes.
            current = 0.0 if direction == UP else 100.0
        self._start_pos = current
        self._start_time = now
        self.direction = direction

    def stop(self, now: float) -> None:
        """Movement stopped at ``now``."""
        self._position = self.position(now)
        self.direction = IDLE

    def tick(self, now: float) -> bool:
        """Settle at an end stop when reached. Return True while still moving."""
        if self.direction == IDLE:
            return False
        pos = self.position(now)
        if pos is not None and (pos >= 100 or pos <= 0):
            self.stop(now)
            return False
        return True

    def pulse_stops(self, direction: int) -> bool:
        """Whether a pulse in ``direction`` stops the current movement."""
        if self.direction == IDLE:
            return False
        if self.stop_method == STOP_SAME:
            return direction == self.direction
        if self.stop_method == STOP_OPPOSITE:
            return direction != self.direction
        return False

    def handle_pulse(self, direction: int, now: float) -> None:
        """A pulse was seen on the bus (wall button or Home Assistant)."""
        self.tick(now)
        if self.pulse_stops(direction):
            self.stop(now)
        elif direction != self.direction:
            self.start(direction, now)

    def time_to(self, target: float, now: float) -> tuple[int, float]:
        """Direction and seconds needed to reach ``target`` from here."""
        pos = self.position(now)
        if pos is None or not self.has_travel_times or abs(target - pos) < 0.5:
            return IDLE, 0.0
        if target > pos:
            return UP, (target - pos) / 100 * self.travel_up
        return DOWN, (pos - target) / 100 * self.travel_down
