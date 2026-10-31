"""
The HAPCan light
"""
from __future__ import annotations
from dis import Instruction
from typing import Optional
from ast import Constant

import json
import voluptuous as vol

# from homeassistant.helpers.entity import ToggleEntity
from homeassistant.components.light import LightEntity, PLATFORM_SCHEMA, ColorMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import logging

from homeassistant.const import (
    CONF_NAME,
    CONF_ADDRESS,
    CONF_DEVICES,
)

from . import DOMAIN, SIGNAL_RELAY_UPDATED
from .hapcan_main import HAPCanEntity, HAPCanConnection
from .const import CONF_HAPCAN_GROUP, CONF_HAPCAN_CHANNEL

_LOGGER = logging.getLogger(__name__)

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.positive_int,
        vol.Required(CONF_HAPCAN_GROUP): cv.positive_int,
        vol.Required(CONF_HAPCAN_CHANNEL): cv.positive_int,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
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
    # def setup_platform(hass, config, add_devices, discovery_info=None):
    """
    Setup the platform
    """
    # _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.debug("HAPCan - call to async_setup_platform")
    _LOGGER.debug(json.dumps(config))
    devices_dict = config["devices"]
    devices = []

    connection = hass.data[DOMAIN]

    for key, value in devices_dict.items():
        devices.append(
            HAPCanRelay(
                key,
                value["name"],
                value["address"],
                value["group"],
                value["channel"],
                connection,
            )
        )

    async_add_entities(devices)
    return


class HAPCanRelayInstruction:
    """
    Class that implements Relay-specific instructions
    """

    COMMAND_TURN_ON = "TurnOn"
    COMMAND_TURN_OFF = "TurnOff"
    COMMAND_TOGGLE = "Toggle"

    channel: int = 0
    instruction: list = []
    command_def: dict = {
        COMMAND_TURN_OFF: 0x00,
        COMMAND_TURN_ON: 0x01,
        COMMAND_TOGGLE: 0x02,
    }

    def __init__(self, command, channel, node, group) -> None:
        self.instruction = []
        self.instruction.append(self.command_def[command])
        self.channel = 0x01 << (channel - 1)
        # self.channel = channel
        self.instruction.append(self.channel)
        self.instruction.append(node)
        self.instruction.append(group)
        self.instruction.extend([0x00, 0x00, 0x00, 0x00])
        _LOGGER.debug("HAPCanRelayInstruction created: %s", str(self.instruction))

    def get_instruction(self) -> list:
        return self.instruction


class HAPCanRelay(HAPCanEntity, LightEntity):
    """Toggle can force update device with sledonline command."""

    _sled_online = None
    
    def __init__(
        self, key, name, address, group, channel, connection: HAPCanConnection
    ) -> None:
        super().__init__(key, name, address, group, channel, connection)
        self.deviceid = "hapcan_relay_" + str(key) + "_" + name
        self._attr_supported_color_modes = {ColorMode.ONOFF}
        self._attr_color_mode = ColorMode.ONOFF

    @property
    def should_poll(self) -> bool:
        # The device itself sends an update of its status
        return False

    @property
    def unique_id(self) -> Optional[str]:
        return self.deviceid

    async def ask_for_status(self):
        instruction = HAPCanRelayInstruction(
            HAPCanRelayInstruction.COMMAND_TURN_OFF,
            self.channel,
            self.address,
            self.group,
        )
        await self._send_status_request(instruction.get_instruction())
        del instruction

    async def async_turn_on(self, **kwargs) -> None:
        instruction = HAPCanRelayInstruction(
            HAPCanRelayInstruction.COMMAND_TURN_ON,
            self.channel,
            self.address,
            self.group,
        )
        await self._send_control_request(instruction.get_instruction())
        del instruction

    async def async_turn_off(self, **kwargs) -> None:
        instruction = HAPCanRelayInstruction(
            HAPCanRelayInstruction.COMMAND_TURN_OFF,
            self.channel,
            self.address,
            self.group,
        )
        await self._send_control_request(instruction.get_instruction())
        del instruction

    async def async_added_to_hass(self):
        """Register callbacks."""
        async_dispatcher_connect(self.hass, SIGNAL_RELAY_UPDATED, self.relay_updated)
        await self.ask_for_status()

    @callback
    def relay_updated(self, message):
        """Update switch state, if needed."""
        _LOGGER.debug("Update relay name: %s message: %s", self.deviceid, message)
        if self.address != message["Node"]:
            _LOGGER.debug("address: %s - %s" % (self.address, message["Node"]))
            return
        if self.group != message["Group"]:
            _LOGGER.debug("group: %s - %s" % (self.group, message["Group"]))
            return
        if self.channel != message["Channel"]:
            _LOGGER.debug("address: %s - %s" % (self.channel, message["Channel"]))
            return
        _LOGGER.debug("That's me!")
        state = message["Status"] == 0xFF
        _LOGGER.debug("State: %s" % str(state))
        self._attr_is_on = state
        self.async_write_ha_state()
