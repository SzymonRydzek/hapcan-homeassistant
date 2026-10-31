"""Travel-time settings for HAPCAN blinds, editable in the Home Assistant UI.

Two number entities per blind (up and down, in seconds). 0 means "not set".
A value set in the UI is remembered across restarts and takes precedence
over ``travel_time_up`` / ``travel_time_down`` in YAML, which only seed it.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .blind_model import DOWN, UP
from .const import DOMAIN


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Create the settings entities for the blinds the cover platform loaded."""
    if discovery_info is None:
        return
    hub = hass.data[DOMAIN]
    entities = []
    for _key, name, cover_uid in discovery_info["covers"]:
        cover = hub.covers[cover_uid]
        entities.append(TravelTime(hub, cover_uid, name, UP, cover.model.travel_up))
        entities.append(TravelTime(hub, cover_uid, name, DOWN, cover.model.travel_down))
    async_add_entities(entities)


class TravelTime(RestoreNumber):
    """Seconds a blind needs for a full movement in one direction."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = 0
    _attr_native_max_value = 300
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, hub, cover_uid: str, name: str, direction: int, yaml_value: float | None
    ) -> None:
        self.hub = hub
        self.cover_uid = cover_uid
        self.direction = direction
        suffix = "up" if direction == UP else "down"
        self._attr_name = f"{name} travel time {suffix}"
        self._attr_unique_id = f"{cover_uid}_travel_time_{suffix}"
        self._attr_native_value = yaml_value or 0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        self._apply()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._apply()
        self.async_write_ha_state()

    def _apply(self) -> None:
        cover = self.hub.covers.get(self.cover_uid)
        if cover is not None:
            cover.set_travel_time(self.direction, self._attr_native_value or None)
