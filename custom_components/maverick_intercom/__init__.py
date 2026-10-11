"""Intercom demonstration using stock Voice Preview firmware."""

import probatio

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .config_flow import validate_endpoint
from .const import DOMAIN, PLATFORMS, SERVICE_HANG_UP, SERVICE_PREPARE
from .controller import IntercomController
from .http import IntercomAudioView

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    devices = {validate_endpoint(hass, item) for item in entry.data["endpoints"].values()}
    if len(devices) != 2:
        raise HomeAssistantError("Choose two distinct ESPHome devices")
    controller = IntercomController(hass, entry)
    entry.runtime_data = controller
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    if not hass.data.get(f"{DOMAIN}_view_registered"):
        hass.http.register_view(IntercomAudioView(hass))
        hass.data[f"{DOMAIN}_view_registered"] = True

    async def handle_service(call: ServiceCall) -> None:
        controllers = list(hass.data[DOMAIN].values())
        if len(controllers) != 1:
            raise HomeAssistantError("Set up the Maverick Intercom demo pair first")
        if call.service == SERVICE_PREPARE:
            await controllers[0].async_prepare()
        else:
            await controllers[0].async_stop()

    for service in (SERVICE_PREPARE, SERVICE_HANG_UP):
        hass.services.async_register(DOMAIN, service, handle_service, schema=probatio.Schema({}))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await controller.async_initialize()
    except Exception:
        await controller.async_close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    await entry.runtime_data.async_close()
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        for service in (SERVICE_PREPARE, SERVICE_HANG_UP):
            hass.services.async_remove(DOMAIN, service)
    return True
