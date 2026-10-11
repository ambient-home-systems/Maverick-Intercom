"""Choose two existing stock ESPHome devices and their Home Assistant LAN URL."""

import probatio

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN
from .controller import validate_base_url


def validate_endpoint(hass, endpoint: dict) -> str:
    registry = er.async_get(hass)
    entries = [registry.async_get(endpoint[key]) for key in ("satellite", "player", "pipeline", "mute")]
    if any(item is None or item.platform != "esphome" or not item.device_id for item in entries):
        raise ValueError("invalid_device")
    if len({item.device_id for item in entries}) != 1:
        raise ValueError("mixed_devices")
    expected = ("assist_satellite", "media_player", "select", "switch")
    if any(item.domain != domain for item, domain in zip(entries, expected, strict=True)):
        raise ValueError("invalid_device")
    if not entries[2].unique_id.endswith("-pipeline"):
        raise ValueError("not_pipeline_selector")
    return entries[0].device_id


def endpoint_schema():
    return probatio.Schema({
        probatio.Required(key): selector.EntitySelector(selector.EntitySelectorConfig(
            filter={"domain": domain, "integration": "esphome"},
        )) for key, domain in (
            ("satellite", "assist_satellite"), ("player", "media_player"),
            ("pipeline", "select"), ("mute", "switch"),
        )
    })


class MaverickConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.endpoints = {}

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self._endpoint_step("a", user_input)

    async def async_step_device_b(self, user_input=None):
        return await self._endpoint_step("b", user_input)

    async def _endpoint_step(self, endpoint, user_input):
        errors = {}
        if user_input is not None:
            try:
                device_id = validate_endpoint(self.hass, user_input)
                if endpoint == "b" and device_id == validate_endpoint(self.hass, self.endpoints["a"]):
                    raise ValueError("same_device")
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self.endpoints[endpoint] = user_input
                if endpoint == "a":
                    return await self.async_step_device_b()
                return await self.async_step_network()
        return self.async_show_form(
            step_id="user" if endpoint == "a" else "device_b",
            data_schema=endpoint_schema(), errors=errors,
        )

    async def async_step_network(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                base_url = validate_base_url(user_input["base_url"])
            except ValueError:
                errors["base_url"] = "invalid_url"
            else:
                await self.async_set_unique_id("stock_voice_demo_pair")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Maverick Intercom", data={"endpoints": self.endpoints, "base_url": base_url},
                )
        try:
            default = get_url(self.hass, prefer_external=False, allow_external=False)
        except NoURLAvailableError:
            default = "http://homeassistant.local:8123"
        return self.async_show_form(
            step_id="network", errors=errors,
            data_schema=probatio.Schema({probatio.Required("base_url", default=default): str}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MaverickOptionsFlow()


class MaverickOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                base_url = validate_base_url(user_input["base_url"])
            except ValueError:
                errors["base_url"] = "invalid_url"
            else:
                return self.async_create_entry(title="", data={"base_url": base_url})
        default = self.config_entry.options.get("base_url", self.config_entry.data["base_url"])
        return self.async_show_form(
            step_id="init", errors=errors,
            data_schema=probatio.Schema({probatio.Required("base_url", default=default): str}),
        )
