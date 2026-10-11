"""Visible call status and bounded-buffer diagnostics, without audio URLs."""

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity

from .const import DOMAIN
from .entity import IntercomEntity

SCAN_INTERVAL = timedelta(seconds=5)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities((IntercomStatus(hass.data[DOMAIN][entry.entry_id]),))


class IntercomStatus(IntercomEntity, SensorEntity):
    _attr_name = "Call status"
    _attr_icon = "mdi:phone"
    _attr_should_poll = True

    def __init__(self, controller) -> None:
        super().__init__(controller, "status")

    @property
    def native_value(self):
        return self.controller.state

    @property
    def extra_state_attributes(self):
        controller = self.controller
        attributes = {
            "last_end_reason": controller.last_reason,
            "pipeline_restoration_pending": bool(controller.pending_restore),
        }
        if session := controller.session:
            for endpoint, audio in session.endpoints.items():
                attributes.update({
                    f"{endpoint}_joined": audio.joined and not session.stopped.is_set(),
                    f"{endpoint}_playback_connected": audio.output_connected and not session.stopped.is_set(),
                    f"{endpoint}_input_bytes": audio.input_bytes,
                    f"{endpoint}_dropped_frames": audio.dropped_frames,
                })
        return attributes
