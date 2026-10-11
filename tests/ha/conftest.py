"""Real HA bootstrap, with device entities represented by local test doubles."""

from pathlib import Path
from types import SimpleNamespace

import pytest_asyncio

from homeassistant import bootstrap, loader
from homeassistant.core import HomeAssistant


@pytest_asyncio.fixture
async def hass(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("UV_CACHE_DIR", str(repository / ".local/uv-cache"))
    monkeypatch.setenv("PIP_CACHE_DIR", str(repository / ".local/pip-cache"))
    (tmp_path / "custom_components").symlink_to(Path(__file__).resolve().parents[2] / "custom_components")
    instance = HomeAssistant(str(tmp_path))
    loader.async_setup(instance)
    configured = await bootstrap.async_from_config_dict({
        "homeassistant": {"name": "Intercom test", "latitude": 0, "longitude": 0,
                          "elevation": 0, "unit_system": "metric", "time_zone": "UTC"},
        "http": {"server_host": "127.0.0.1", "server_port": 8124},
        "assist_pipeline": {}, "stt": {}, "media_player": {}, "select": {},
    }, instance)
    assert configured is instance
    await instance.async_block_till_done()
    yield instance
    await instance.async_stop(force=True)


@pytest_asyncio.fixture
async def controller(hass):
    from custom_components.maverick_intercom.controller import IntercomController

    pair = {endpoint: {"satellite": f"assist_satellite.{endpoint}",
                       "player": f"media_player.{endpoint}",
                       "pipeline": f"select.{endpoint}", "mute": f"switch.{endpoint}_mute"}
            for endpoint in ("a", "b")}
    entry = SimpleNamespace(entry_id="demo", data={"endpoints": pair, "base_url": "http://ha.local:8123"}, options={})
    result = IntercomController(hass, entry)
    hass.data.setdefault("maverick_intercom", {})[entry.entry_id] = result
    for endpoint, config in pair.items():
        hass.states.async_set(config["satellite"], "idle")
        hass.states.async_set(config["player"], "idle")
        hass.states.async_set(config["mute"], "off")
        hass.states.async_set(config["pipeline"], "preferred", {"options": ["preferred"]})
    await result.async_initialize()
    yield result
    await result.async_close()
