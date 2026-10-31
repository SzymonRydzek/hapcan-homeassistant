from homeassistant.components.cover import CoverEntity, PLATFORM_SCHEMA

import json
import voluptuous as vol
import time
import asyncio

from .light import HAPCanRelayInstruction
from . import DOMAIN, SIGNAL_RELAY_UPDATED
from .hapcan_main import HAPCanEntity, HAPCanConnection
from .const import CONF_HAPCAN_GROUP, CONF_HAPCAN_CHANNEL_UP, CONF_HAPCAN_CHANNEL_DOWN

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

_LOGGER = logging.getLogger(__name__)
directions = {"up" : 1, "down" : 2, "stop" : 3}

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ADDRESS): cv.positive_int,
        vol.Required(CONF_HAPCAN_GROUP): cv.positive_int,
        vol.Required(CONF_HAPCAN_CHANNEL_UP): cv.positive_int,
        vol.Required(CONF_HAPCAN_CHANNEL_DOWN): cv.positive_int,
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
    _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.debug("HAPCan - call to async_setup_platform")
    _LOGGER.debug(json.dumps(config))
    devices_dict = config["devices"]
    devices = []

    connection = hass.data[DOMAIN]

    for key, value in devices_dict.items():
        devices.append(
            HAPCanCover(
                key,
                value["name"],
                value["address"],
                value["group"],
                value["channel_up"],
                value["channel_down"],
                connection,
            )
        )

    async_add_entities(devices)
    return

# async def async_setup_entry(hass, config_entry, async_add_entities):
#     async_add_entities([HAPCanCover()])

class HAPCanCover(HAPCanEntity, CoverEntity):
    """Toggle can force update device with sledonline command."""

    _sled_online = None
    channel_down: int = 0
    _direction: int = directions["stop"]
    
    def __init__(
        self, key, name, address, group, channel_up, channel_down, connection: HAPCanConnection
    ) -> None:
        super().__init__(key, name, address, group, channel_up, connection)
        self.deviceid = "hapcan_cover_" + str(key) + "_" + name
        self.channel_down = channel_down
        self._is_closed = None
        self._current_position = 50
    
    async def _go_up(self):
        _LOGGER.debug("HAPCan - close relay")
        instruction = HAPCanRelayInstruction(
            HAPCanRelayInstruction.COMMAND_TURN_ON,
            self.channel,
            self.address,
            self.group,
        )
        await self._send_control_request(instruction.get_instruction())
        del instruction
        #time.sleep(0.2)
        await asyncio.sleep(0.2)

        _LOGGER.debug("HAPCan - open relay")
        instruction = HAPCanRelayInstruction(
            HAPCanRelayInstruction.COMMAND_TURN_OFF,
            self.channel,
            self.address,
            self.group,
        )
        await self._send_control_request(instruction.get_instruction())
        del instruction
    
    async def _go_down(self):
        _LOGGER.debug("HAPCan - close relay")
        instruction = HAPCanRelayInstruction(
            HAPCanRelayInstruction.COMMAND_TURN_ON,
            self.channel_down,
            self.address,
            self.group,
        )
        await self._send_control_request(instruction.get_instruction())
        del instruction
        #time.sleep(0.2)
        await asyncio.sleep(0.2)

        _LOGGER.debug("HAPCan - open relay")
        instruction = HAPCanRelayInstruction(
            HAPCanRelayInstruction.COMMAND_TURN_OFF,
            self.channel_down,
            self.address,
            self.group,
        )
        await self._send_control_request(instruction.get_instruction())
        del instruction

    @property
    def is_closed(self):
        return self._is_closed

    @property
    def current_cover_position(self):
        return self._current_position

    async def async_open_cover(self, **kwargs):
        # Implement code to open the cover here
        _LOGGER.debug("HAPCan - Trying to open")
        await self._go_up()
        self._is_closed = False
        self._current_position = 0

    async def async_close_cover(self, **kwargs):
        # Implement code to close the cover here
        _LOGGER.debug("HAPCan - Trying to close")
        await self._go_down()
        self._is_closed = True
        self._current_position = 100

    async def async_set_cover_position(self, **kwargs):
        # Implement code to set the cover position here
        self._current_position = kwargs['position']

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        # This will need position counter so that
        # we know that the blind finally stopped
        # after moving up and then resetting the
        # direction. Otherwise calling stop on open
        # blind will cause closing.
        pass