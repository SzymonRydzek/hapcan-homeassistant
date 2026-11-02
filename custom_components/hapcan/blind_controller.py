"""Blinds on a HAPCAN blind controller module (UNIV 3.7.0.x, up to 3 channels).

The module drives the motor itself and estimates the blind position from its
configured running time. It reports position and movement on the bus when a
motor starts or stops, and answers status requests with the live estimate.
While a blind moves, its status is polled once a second so the position in
Home Assistant follows it, and a requested position is reached by stopping
the motor when the reported position gets there.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.components.cover import ATTR_POSITION, CoverEntity, CoverEntityFeature
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval

from . import protocol
from .blind_model import DOWN, IDLE, UP, controller_should_stop
from .const import CONF_HAPCAN_CHANNEL, CONF_HAPCAN_GROUP, SIGNAL_BLIND_UPDATED
from .entity import HapcanEntity

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(seconds=1)
# Positions this close to the target count as reached.
TOLERANCE = 2
# A reversal makes the module stop, wait 1 s and start again; a "stopped"
# report within this window after our command does not cancel the target.
REVERSAL_GRACE = 2.5


class HapcanBlindController(HapcanEntity, CoverEntity):
    """One channel of a HAPCAN blind controller."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, hub, key: int, dev: dict[str, Any]) -> None:
        super().__init__(hub, dev[CONF_NAME], dev[CONF_ADDRESS], dev[CONF_HAPCAN_GROUP])
        self.channel: int = dev[CONF_HAPCAN_CHANNEL]
        self._attr_unique_id = (
            f"hapcan_blind_{self.node:02x}{self.module_group:02x}_{self.channel}"
        )
        self._position: int | None = None
        self._move = protocol.BLIND_MOVE_STOPPED
        self._target: int | None = None
        self._target_direction = IDLE
        self._step = 0.0
        self._command_time = 0.0
        self._unsub_poll = None

    # --- state -----------------------------------------------------------

    @property
    def current_cover_position(self) -> int | None:
        return self._position

    @property
    def is_closed(self) -> bool | None:
        return None if self._position is None else self._position == 0

    @property
    def is_opening(self) -> bool:
        return self._move == protocol.BLIND_MOVE_UP

    @property
    def is_closing(self) -> bool:
        return self._move == protocol.BLIND_MOVE_DOWN

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_BLIND_UPDATED, self._blind_status)
        )

    async def async_will_remove_from_hass(self) -> None:
        self._stop_polling()
        await super().async_will_remove_from_hass()

    # --- commands --------------------------------------------------------

    async def async_open_cover(self, **kwargs: Any) -> None:
        self._target = None
        await self._run(protocol.BLIND_UP)

    async def async_close_cover(self, **kwargs: Any) -> None:
        self._target = None
        await self._run(protocol.BLIND_DOWN)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        self._target = None
        await self._run(protocol.BLIND_STOP)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        target = int(kwargs[ATTR_POSITION])
        current = self._position
        if target >= 100 or target <= 0 or current is None:
            # End positions need no stop; an unknown start runs to the nearer end.
            self._target = None
            await self._run(protocol.BLIND_UP if target >= 50 else protocol.BLIND_DOWN)
            return
        if abs(target - current) <= TOLERANCE:
            return
        self._target = target
        self._target_direction = UP if target > current else DOWN
        self._step = 0.0
        await self._run(protocol.BLIND_UP if target > current else protocol.BLIND_DOWN)
        self._start_polling()

    async def _run(self, instruction: int) -> None:
        self._command_time = time.monotonic()
        await self._send(
            protocol.blind_control_frame(instruction, self.channel, self.node, self.module_group)
        )

    # --- bus frames ------------------------------------------------------

    @callback
    def _blind_status(self, status: protocol.BlindStatus) -> None:
        if (status.node, status.group, status.channel) != (
            self.node,
            self.module_group,
            self.channel,
        ):
            return
        previous = self._position
        self._position = status.position
        self._move = status.move
        if previous is not None and status.move != protocol.BLIND_MOVE_STOPPED:
            self._step = abs(status.position - previous) or self._step

        if status.move == protocol.BLIND_MOVE_STOPPED:
            if self._target is None or time.monotonic() - self._command_time > REVERSAL_GRACE:
                self._target = None
                self._stop_polling()
        else:
            self._start_polling()
            if self._target is not None and controller_should_stop(
                self._target_direction, status.position, self._target, self._step
            ):
                self._target = None
                self.hass.async_create_task(self._run(protocol.BLIND_STOP))
        self.async_write_ha_state()

    # --- polling while moving ---------------------------------------------

    async def _poll(self, _now=None) -> None:
        try:
            await self.hub.connection.send(
                protocol.status_request_frame(self.node, self.module_group)
            )
        except ConnectionError:
            self._stop_polling()

    def _start_polling(self) -> None:
        if self._unsub_poll is None:
            self._unsub_poll = async_track_time_interval(self.hass, self._poll, POLL_INTERVAL)

    def _stop_polling(self) -> None:
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None
