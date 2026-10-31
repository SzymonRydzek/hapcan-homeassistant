"""HAPCAN home automation bus integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .connection import HapcanConnection
from .const import DEFAULT_PORT, DOMAIN, SIGNAL_CONNECTION, SIGNAL_RELAY_UPDATED
from .protocol import RelayStatus, status_request_frame

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class HapcanHub:
    """Shared state: the connection plus the modules entities live on."""

    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        self.hass = hass
        self.modules: set[tuple[int, int]] = set()
        self.connection = HapcanConnection(
            host,
            port,
            on_relay_status=self._relay_status,
            on_connection_change=self._connection_change,
            modules=lambda: self.modules,
        )

    @property
    def connected(self) -> bool:
        return self.connection.connected

    @callback
    def _relay_status(self, status: RelayStatus) -> None:
        async_dispatcher_send(self.hass, SIGNAL_RELAY_UPDATED, status)

    @callback
    def _connection_change(self, connected: bool) -> None:
        async_dispatcher_send(self.hass, SIGNAL_CONNECTION, connected)

    async def async_register_module(self, node: int, group: int) -> None:
        """Remember a module and, if already connected, ask for its state."""
        if (node, group) in self.modules:
            return
        self.modules.add((node, group))
        if self.connected:
            try:
                await self.connection.send(status_request_frame(node, group))
            except ConnectionError:
                pass  # requested again on the next connect


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the HAPCAN connection from configuration.yaml."""
    conf = config[DOMAIN]
    hub = HapcanHub(hass, conf[CONF_HOST], conf[CONF_PORT])
    hass.data[DOMAIN] = hub

    task = hass.async_create_background_task(
        hub.connection.run(), name="hapcan connection"
    )

    async def _stop(_: Event) -> None:
        await hub.connection.close()
        task.cancel()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop)
    return True
