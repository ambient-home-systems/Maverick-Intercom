"""Shared device and controller state for demo controls."""

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


class IntercomEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller, key: str) -> None:
        self.controller = controller
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)}, name="Maverick Intercom",
            manufacturer="Maverick", model="Stock Voice Preview demo",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.listen(self.async_write_ha_state))
