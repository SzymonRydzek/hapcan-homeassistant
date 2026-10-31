import voluptuous as vol
import logging
import json

from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.core import callback, HomeAssistant

from .hapcan_main import HAPCanConnection


from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
)
from homeassistant.helpers import config_validation as cv

DOMAIN = "hapcan"
DEFAULT_PORT = 1004

SIGNAL_RELAY_UPDATED = "hapcan.relay_updated"

_LOGGER = logging.getLogger(__name__)


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            },
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, hass_config: ConfigType) -> bool:

    config = hass_config[DOMAIN]

    # _LOGGER.setLevel(logging.DEBUG)

    _LOGGER.debug(json.dumps(config))

    host = config.get(CONF_HOST, "no_host")
    port = config.get(CONF_PORT, 1005)

    _LOGGER.debug("HAPCan host: %s:%s ", host, port)

    @callback
    def relay_update_callback(status):
        """Update status of the relay"""
        _LOGGER.debug("Relay callback, status: %s", status)
        async_dispatcher_send(hass, SIGNAL_RELAY_UPDATED, status)

    session = async_get_clientsession(hass)
    hass.data[DOMAIN] = connection = HAPCanConnection(session, host, port, hass.loop)

    await connection.open()

    hass.loop.create_task(connection.monitor_status(relay_update_callback))

    return True
