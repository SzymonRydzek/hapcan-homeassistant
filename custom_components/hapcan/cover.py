"""Blinds driven by two monostable HAPCAN relay channels (up and down).

Each command is a short pulse on one channel, which is what the motor
controller (e.g. Mobilus contact inputs) expects. The blind does not report
its position, so it is estimated from travel times when they are configured.
Pulses from wall buttons are seen on the bus and update the estimate too.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.components.cover import (
    ATTR_POSITION,
    PLATFORM_SCHEMA,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import CONF_ADDRESS, CONF_DEVICES, CONF_NAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import protocol
from .blind_model import DOWN, IDLE, UP, BlindModel
from .const import (
    CONF_HAPCAN_CHANNEL_DOWN,
    CONF_HAPCAN_CHANNEL_UP,
    CONF_HAPCAN_GROUP,
    CONF_STOP_METHOD,
    CONF_TRAVEL_TIME_DOWN,
    CONF_TRAVEL_TIME_UP,
    DOMAIN,
    PULSE_SECONDS,
    STOP_NONE,
    STOP_OPPOSITE,
    STOP_SAME,
)
from .entity import HapcanEntity

_LOGGER = logging.getLogger(__name__)

# Relay frames echoing our own pulse arrive within this window and are ignored.
OWN_PULSE_WINDOW = 1.5
UPDATE_INTERVAL = timedelta(seconds=1)

CHANNEL = vol.All(vol.Coerce(int), vol.Range(min=1, max=8))
STOP_METHODS = vol.In([STOP_NONE, STOP_OPPOSITE, STOP_SAME])

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.positive_int,
        vol.Required(CONF_HAPCAN_GROUP): cv.positive_int,
        vol.Required(CONF_HAPCAN_CHANNEL_UP): CHANNEL,
        vol.Required(CONF_HAPCAN_CHANNEL_DOWN): CHANNEL,
        vol.Optional(CONF_TRAVEL_TIME_UP): vol.All(vol.Coerce(float), vol.Range(min=1)),
        vol.Optional(CONF_TRAVEL_TIME_DOWN): vol.All(vol.Coerce(float), vol.Range(min=1)),
        vol.Optional(CONF_STOP_METHOD): STOP_METHODS,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        # Default for every blind of this platform; a device may override it.
        vol.Optional(CONF_STOP_METHOD, default=STOP_NONE): STOP_METHODS,
        vol.Optional(CONF_DEVICES, default={}): {vol.Coerce(int): DEVICE_SCHEMA},
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up HAPCAN blinds from YAML, plus their travel-time settings."""
    hub = hass.data[DOMAIN]
    covers = [
        HapcanCover(hub, key, {CONF_STOP_METHOD: config[CONF_STOP_METHOD], **dev})
        for key, dev in config[CONF_DEVICES].items()
    ]
    async_add_entities(covers)
    hass.async_create_task(
        async_load_platform(
            hass, Platform.NUMBER, DOMAIN, {"covers": [c.settings_key for c in covers]}, hub.hass_config
        )
    )


class HapcanCover(HapcanEntity, CoverEntity, RestoreEntity):
    """A blind moved by pulses on an up and a down relay channel."""

    _attr_assumed_state = True

    def __init__(self, hub, key: int, dev: dict[str, Any]) -> None:
        super().__init__(hub, dev[CONF_NAME], dev[CONF_ADDRESS], dev[CONF_HAPCAN_GROUP])
        self.channel_up: int = dev[CONF_HAPCAN_CHANNEL_UP]
        self.channel_down: int = dev[CONF_HAPCAN_CHANNEL_DOWN]
        # Kept identical to the original integration so entity IDs survive.
        self._attr_unique_id = f"hapcan_cover_{key}_{dev[CONF_NAME]}"
        self.model = BlindModel(
            dev.get(CONF_TRAVEL_TIME_UP),
            dev.get(CONF_TRAVEL_TIME_DOWN),
            dev[CONF_STOP_METHOD],
        )
        # Identifies this blind to its travel-time number entities.
        self.settings_key = (key, dev[CONF_NAME], self._attr_unique_id)
        hub.covers[self._attr_unique_id] = self
        self._own_pulse_until: dict[int, float] = {}
        self._unsub_tick = None
        self._unsub_target = None

    # --- state -----------------------------------------------------------

    @property
    def supported_features(self) -> CoverEntityFeature:
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if self._can_stop:
            features |= CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
        return features

    @property
    def _can_stop(self) -> bool:
        return self.model.can_stop and self.model.has_travel_times

    @callback
    def set_travel_time(self, direction: int, seconds: float | None) -> None:
        """Apply a travel time changed in the UI (None or 0 = not set)."""
        now = time.monotonic()
        self.model.tick(now)
        if self.model.direction != IDLE:
            self.model.stop(now)  # keep the estimate consistent
            self._stop_ticking()
        if direction == UP:
            self.model.travel_up = seconds or None
        else:
            self.model.travel_down = seconds or None
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def current_cover_position(self) -> int | None:
        if not self.model.has_travel_times:
            return None
        pos = self.model.position(time.monotonic())
        return None if pos is None else round(pos)

    @property
    def is_closed(self) -> bool | None:
        return self.model.is_closed(time.monotonic())

    @property
    def is_opening(self) -> bool:
        return self.model.direction == UP

    @property
    def is_closing(self) -> bool:
        return self.model.direction == DOWN

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        pos = last.attributes.get("current_position")
        if pos is not None:
            self.model._position = float(pos)
        elif last.state in ("open", "closed"):
            self.model._position = 100.0 if last.state == "open" else 0.0

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timers()
        await super().async_will_remove_from_hass()

    # --- commands --------------------------------------------------------

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._move(UP)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._move(DOWN)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._stop()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        target = float(kwargs[ATTR_POSITION])
        now = time.monotonic()
        self.model.tick(now)
        if self.model.direction != IDLE:
            await self._stop()
        direction, seconds = self.model.time_to(target, time.monotonic())
        if direction == IDLE:
            return
        await self._move(direction)
        if target in (0, 100):
            return  # runs to the end stop, no stop pulse needed

        async def _arrive(_now) -> None:
            self._unsub_target = None
            await self._stop()

        self._unsub_target = async_call_later(self.hass, seconds, _arrive)

    async def _move(self, direction: int) -> None:
        now = time.monotonic()
        self.model.tick(now)
        timed = self.model.has_travel_times
        if timed and self.model.direction == direction:
            return  # already on its way
        if timed and self.model.direction != IDLE and self.model.stop_method == STOP_OPPOSITE:
            # An opposite pulse would only stop it: stop first, then reverse.
            await self._stop()
        await self._pulse(self.channel_up if direction == UP else self.channel_down)
        self.model.start(direction, time.monotonic())
        self._start_ticking()
        self.async_write_ha_state()

    async def _stop(self) -> None:
        self._cancel_target()
        now = time.monotonic()
        self.model.tick(now)
        # Without travel times we cannot tell whether it is still moving, and
        # a stop pulse sent to a stopped blind would start it again.
        if self.model.direction == IDLE or not self._can_stop:
            return
        if self.model.stop_method == STOP_SAME:
            channel = self.channel_up if self.model.direction == UP else self.channel_down
        else:
            channel = self.channel_down if self.model.direction == UP else self.channel_up
        await self._pulse(channel)
        self.model.stop(time.monotonic())
        self._stop_ticking()
        self.async_write_ha_state()

    async def _pulse(self, channel: int) -> None:
        self._own_pulse_until[channel] = time.monotonic() + OWN_PULSE_WINDOW
        await self._send(
            protocol.relay_control_frame(protocol.RELAY_ON, channel, self.node, self.module_group)
        )
        await asyncio.sleep(PULSE_SECONDS)
        await self._send(
            protocol.relay_control_frame(protocol.RELAY_OFF, channel, self.node, self.module_group)
        )

    # --- bus frames from wall buttons -------------------------------------

    @callback
    def handle_relay_status(self, status: protocol.RelayStatus) -> None:
        if not status.is_on or status.channel not in (self.channel_up, self.channel_down):
            return
        now = time.monotonic()
        if now < self._own_pulse_until.get(status.channel, 0):
            return  # echo of our own command
        self._cancel_target()
        direction = UP if status.channel == self.channel_up else DOWN
        self.model.handle_pulse(direction, now)
        if self.model.direction != IDLE:
            self._start_ticking()
        else:
            self._stop_ticking()
        self.async_write_ha_state()

    # --- progress updates -------------------------------------------------

    @callback
    def _tick(self, _now=None) -> None:
        if not self.model.tick(time.monotonic()):
            self._stop_ticking()
        self.async_write_ha_state()

    def _start_ticking(self) -> None:
        if self._unsub_tick is None and self.model.direction != IDLE:
            self._unsub_tick = async_track_time_interval(self.hass, self._tick, UPDATE_INTERVAL)

    def _stop_ticking(self) -> None:
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None

    def _cancel_target(self) -> None:
        if self._unsub_target is not None:
            self._unsub_target()
            self._unsub_target = None

    def _cancel_timers(self) -> None:
        self._stop_ticking()
        self._cancel_target()
