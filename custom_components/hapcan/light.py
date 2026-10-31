"""Lights on HAPCAN relay modules (one relay channel per light)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.light import PLATFORM_SCHEMA, ColorMode, LightEntity
from homeassistant.const import CONF_ADDRESS, CONF_DEVICES, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import protocol
from .const import CONF_HAPCAN_CHANNEL, CONF_HAPCAN_GROUP, DOMAIN
from .entity import HapcanEntity

_LOGGER = logging.getLogger(__name__)

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.positive_int,
        vol.Required(CONF_HAPCAN_GROUP): cv.positive_int,
        vol.Required(CONF_HAPCAN_CHANNEL): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Optional(CONF_DEVICES, default={}): {vol.Coerce(int): DEVICE_SCHEMA}},
    extra=vol.ALLOW_EXTRA,
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up HAPCAN lights from YAML."""
    hub = hass.data[DOMAIN]
    async_add_entities(
        HapcanLight(
            hub,
            key,
            dev[CONF_NAME],
            dev[CONF_ADDRESS],
            dev[CONF_HAPCAN_GROUP],
            dev[CONF_HAPCAN_CHANNEL],
        )
        for key, dev in config[CONF_DEVICES].items()
    )


class HapcanLight(HapcanEntity, LightEntity):
    """A light switched by one HAPCAN relay channel."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, hub, key: int, name: str, node: int, group: int, channel: int) -> None:
        super().__init__(hub, name, node, group)
        self.channel = channel
        # Kept identical to the original integration so entity IDs survive.
        self._attr_unique_id = f"hapcan_relay_{key}_{name}"

    @callback
    def handle_relay_status(self, status: protocol.RelayStatus) -> None:
        if status.channel != self.channel:
            return
        self._attr_is_on = status.is_on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(
            protocol.relay_control_frame(protocol.RELAY_ON, self.channel, self.node, self.group)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(
            protocol.relay_control_frame(protocol.RELAY_OFF, self.channel, self.node, self.group)
        )
