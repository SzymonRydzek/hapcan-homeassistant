"""Base entity shared by HAPCAN lights and covers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import SIGNAL_CONNECTION, SIGNAL_RELAY_UPDATED
from .protocol import RelayStatus

if TYPE_CHECKING:
    from . import HapcanHub


class HapcanEntity(Entity):
    """Entity on a HAPCAN relay module, updated by frames pushed from the bus."""

    _attr_should_poll = False

    def __init__(self, hub: HapcanHub, name: str, node: int, group: int) -> None:
        self.hub = hub
        self.node = node
        self.module_group = group
        self._attr_name = name

    @property
    def available(self) -> bool:
        return self.hub.connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_RELAY_UPDATED, self._relay_status)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CONNECTION, self._connection_change)
        )
        await self.hub.async_register_module(self.node, self.module_group)

    @callback
    def _relay_status(self, status: RelayStatus) -> None:
        if status.node == self.node and status.group == self.module_group:
            self.handle_relay_status(status)

    @callback
    def handle_relay_status(self, status: RelayStatus) -> None:
        """Handle a status frame from this entity's module."""

    @callback
    def _connection_change(self, connected: bool) -> None:
        self.async_write_ha_state()

    async def _send(self, frame: bytes) -> None:
        try:
            await self.hub.connection.send(frame)
        except ConnectionError as err:
            raise HomeAssistantError(f"HAPCAN not connected: {err}") from err
