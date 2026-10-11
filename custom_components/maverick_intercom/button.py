"""Prepare and hang-up controls for an explicit-join demo."""

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .entity import IntercomEntity


async def async_setup_entry(hass, entry, async_add_entities):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities((IntercomButton(controller, False), IntercomButton(controller, True)))


class IntercomButton(IntercomEntity, ButtonEntity):
    def __init__(self, controller, hang_up: bool) -> None:
        super().__init__(controller, "hang_up" if hang_up else "prepare")
        self.hang_up = hang_up
        self._attr_name = "Hang up" if hang_up else "Prepare call"
        self._attr_icon = "mdi:phone-hangup" if hang_up else "mdi:phone-in-talk"

    async def async_press(self) -> None:
        if self.hang_up:
            await self.controller.async_stop()
        else:
            await self.controller.async_prepare()
