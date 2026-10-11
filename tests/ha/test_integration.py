"""Load the real HA integration and run its pipelines beyond VAD's limit."""

import asyncio
from types import MappingProxyType

import probatio
import pytest

from homeassistant.components import stt, tts
from homeassistant.components.assist_pipeline import (
    PipelineStage, async_get_pipelines, async_pipeline_from_audio_stream,
)
from homeassistant.components.assist_pipeline.pipeline import async_create_default_pipeline
from homeassistant.components.media_player.const import MEDIA_PLAYER_PLAY_MEDIA_SCHEMA
from homeassistant.components.tts.const import DATA_COMPONENT as TTS_COMPONENT
from homeassistant.config_entries import ConfigEntry, ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.translation import async_get_translations

from custom_components.maverick_intercom.audio import SILENCE
from custom_components.maverick_intercom.const import DOMAIN
from custom_components.maverick_intercom.config_flow import validate_endpoint
from custom_components.maverick_intercom.stt import IntercomAudioProvider


def entry(domain, data, *, disabled=False):
    return ConfigEntry(
        version=1, minor_version=1, domain=domain, title=domain, data=data,
        options={}, source="user", unique_id=None, discovery_keys=MappingProxyType({}),
        subentries_data=(), disabled_by=ConfigEntryDisabler.USER if disabled else None,
    )


async def stock_registry(hass):
    pair = {}
    for endpoint in ("a", "b"):
        stock = entry("esphome", {"host": "example.invalid"}, disabled=True)
        await hass.config_entries.async_add(stock)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=stock.entry_id, identifiers={("esphome", endpoint)},
            name=f"Voice Preview {endpoint.upper()}",
        )
        pair[endpoint] = {}
        for key, domain, unique in (
            ("satellite", "assist_satellite", f"{endpoint}-assist_satellite"),
            ("player", "media_player", f"{endpoint}-media-player"),
            ("pipeline", "select", f"{endpoint}-pipeline"),
            ("mute", "switch", f"{endpoint}-mute"),
        ):
            entity = er.async_get(hass).async_get_or_create(
                domain, "esphome", unique, suggested_object_id=f"demo_{endpoint}_{key}",
                config_entry=stock, device_id=device.id,
            )
            pair[endpoint][key] = entity.entity_id
            hass.states.async_set(entity.entity_id, "off" if key == "mute" else "idle")
    return pair


class FakeTTS(tts.TextToSpeechEntity):
    _attr_name = "Demo TTS"
    _attr_default_language = "en"
    _attr_supported_languages = ["en"]

    async def async_get_tts_audio(self, message, language, options=None):
        raise AssertionError("Intercom must not reach speech synthesis")


class FakeNormalSTT(IntercomAudioProvider):
    async def async_added_to_hass(self):
        await stt.SpeechToTextEntity.async_added_to_hass(self)

    async def async_will_remove_from_hass(self):
        await stt.SpeechToTextEntity.async_will_remove_from_hass(self)

    async def async_process_audio_stream(self, metadata, stream):
        raise AssertionError("An intercom call must select its dedicated audio provider")


@pytest.mark.asyncio
async def test_config_flow_validates_pair_and_lan_address(hass):
    pair = await stock_registry(hass)
    assert validate_endpoint(hass, pair["a"]) != validate_endpoint(hass, pair["b"])
    first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert first["step_id"] == "user"
    second = await hass.config_entries.flow.async_configure(first["flow_id"], pair["a"])
    assert second["step_id"] == "device_b"
    same = await hass.config_entries.flow.async_configure(first["flow_id"], pair["a"])
    assert same["errors"]["base"] == "same_device"
    network = await hass.config_entries.flow.async_configure(first["flow_id"], pair["b"])
    assert network["step_id"] == "network"
    invalid = await hass.config_entries.flow.async_configure(first["flow_id"], {"base_url": "http://user:password@host"})
    assert invalid["errors"]["base_url"] == "invalid_url"
    translations = await async_get_translations(hass, "en", "config", {DOMAIN})
    prefix = f"component.{DOMAIN}.config"
    assert translations[f"{prefix}.step.network.data.base_url"]
    assert translations[f"{prefix}.error.same_device"]
    created = await hass.config_entries.flow.async_configure(
        first["flow_id"], {"base_url": "http://ha.local:8123"},
    )
    await hass.async_block_till_done()
    configured = created["result"]
    assert configured.state is ConfigEntryState.LOADED
    original_controller = configured.runtime_data
    options = await hass.config_entries.options.async_init(configured.entry_id)
    changed = await hass.config_entries.options.async_configure(
        options["flow_id"], {"base_url": "http://192.168.1.20:8123"},
    )
    await hass.async_block_till_done()
    assert changed["data"]["base_url"] == "http://192.168.1.20:8123"
    assert configured.runtime_data is not original_controller
    assert configured.runtime_data.base_url == "http://192.168.1.20:8123"
    assert await hass.config_entries.async_unload(configured.entry_id)


@pytest.mark.asyncio
async def test_real_entry_pipeline_creation_streaming_and_unload(hass):
    pair = await stock_registry(hass)
    integration = entry(DOMAIN, {"endpoints": pair, "base_url": "http://ha.local:8123"})
    await hass.config_entries.async_add(integration)
    await hass.async_block_till_done()
    assert integration.state is ConfigEntryState.LOADED
    controller = integration.runtime_data
    assert set(controller.provider_ids) == {"a", "b"}
    assert len([state for state in hass.states.async_all() if state.domain == "button"]) == 2

    voice = FakeTTS()
    await hass.data[TTS_COMPONENT].async_add_entities((voice,))
    normal_stt = FakeNormalSTT(controller, "normal_test")
    await hass.data[stt.DATA_COMPONENT].async_add_entities((normal_stt,))
    normal = await async_create_default_pipeline(
        hass, normal_stt.entity_id, voice.entity_id, "Normal test assist",
    )
    assert normal is not None
    for config in pair.values():
        hass.states.async_set(config["pipeline"], normal.name)

    playback_calls = []

    async def select(call):
        assert call.data["option"] in {item.name for item in async_get_pipelines(hass)}
        hass.states.async_set(call.data["entity_id"], call.data["option"], context=call.context)

    async def play(call):
        # Use HA's real play_media fields schema, not a permissive mock.
        fields = {key: value for key, value in call.data.items() if key != "entity_id"}
        probatio.Schema(MEDIA_PLAYER_PLAY_MEDIA_SCHEMA)(fields)
        playback_calls.append(call.data)

    hass.services.async_register("select", "select_option", select)
    hass.services.async_register("media_player", "play_media", play)
    await hass.services.async_call(DOMAIN, "prepare", {}, blocking=True)
    assert controller.state == "armed"
    pipelines = {item.name: item for item in async_get_pipelines(hass)}
    for endpoint in ("a", "b"):
        assert pipelines[controller.pipeline_name(endpoint)].stt_engine == controller.provider_ids[endpoint]
        provider = stt.async_get_speech_to_text_entity(hass, controller.provider_ids[endpoint])
        assert provider.audio_processing.requires_external_vad is False

    completed_audio = {endpoint: asyncio.Event() for endpoint in ("a", "b")}
    block = asyncio.Event()
    events = {endpoint: [] for endpoint in ("a", "b")}

    async def source(endpoint):
        # 20 seconds of samples, including silence, exceed stock HA's 15-second
        # utterance segmenter limit. Accelerate delivery; this tests pipeline
        # lifecycle, not acoustic latency or a physical microphone.
        for _ in range(1000):
            yield SILENCE
            await asyncio.sleep(0)
        completed_audio[endpoint].set()
        await block.wait()

    tasks = []
    for endpoint in ("a", "b"):
        pipeline = pipelines[controller.pipeline_name(endpoint)]
        tasks.append(asyncio.create_task(async_pipeline_from_audio_stream(
            hass, context=Context(), event_callback=events[endpoint].append,
            stt_metadata=stt.SpeechMetadata(
                language="en", format=stt.AudioFormats.WAV, codec=stt.AudioCodecs.PCM,
                bit_rate=stt.AudioBitRates.BITRATE_16,
                sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
                channel=stt.AudioChannels.CHANNEL_MONO,
            ),
            stt_stream=source(endpoint), pipeline_id=pipeline.id,
            start_stage=PipelineStage.STT, end_stage=PipelineStage.TTS,
        )))
    try:
        await asyncio.wait_for(asyncio.gather(*(item.wait() for item in completed_audio.values())), 5)
        assert all(not task.done() for task in tasks)
        assert controller.session.active
        assert all(audio.input_bytes > 600000 for audio in controller.session.endpoints.values())
        await hass.services.async_call(DOMAIN, "hang_up", {}, blocking=True)
        await asyncio.wait_for(asyncio.gather(*tasks), 2)
        for emitted in events.values():
            kinds = {event.type.value for event in emitted}
            assert "run-end" in kinds
            assert "intent-start" not in kinds
            assert "tts-start" not in kinds
        assert all(hass.states.get(config["pipeline"]).state == normal.name for config in pair.values())
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    # Never save a leftover intercom selection as the device's normal Assist.
    hass.states.async_set(pair["a"]["pipeline"], controller.pipeline_name("a"))
    with pytest.raises(HomeAssistantError, match="working normal Assist"):
        await controller.async_prepare()
    assert controller.state == "idle"
    assert not controller.pending_restore
    hass.states.async_set(pair["a"]["pipeline"], normal.name)
    assert await hass.config_entries.async_unload(integration.entry_id)
    assert integration.entry_id not in hass.data[DOMAIN]
    assert not hass.services.has_service(DOMAIN, "prepare")
