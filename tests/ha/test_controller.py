"""Exercise restoration and HA events with a real Home Assistant runtime."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.maverick_intercom.controller import IntercomController


async def install_services(controller, fail_b=False):
    hass = controller.hass
    calls = []

    async def select(call):
        if fail_b and call.data["entity_id"] == "select.b" and call.data["option"] != "preferred":
            raise HomeAssistantError("device disconnected")
        hass.states.async_set(call.data["entity_id"], call.data["option"], context=call.context)

    async def playback(call):
        calls.append(dict(call.data))

    hass.services.async_register("select", "select_option", select)
    hass.services.async_register("media_player", "play_media", playback)
    controller._ensure_pipelines = AsyncMock()
    return calls


@pytest.mark.asyncio
async def test_prepare_and_hangup_restore_both_original_selections(controller):
    await install_services(controller)
    await controller.async_prepare()
    assert controller.state == "armed"
    assert controller.hass.states.get("select.a").state == "Maverick Intercom A"
    assert len(await controller._store.async_load()) == 2
    await controller.async_stop()
    assert controller.state == "idle"
    assert controller.hass.states.get("select.a").state == "preferred"
    assert controller.hass.states.get("select.b").state == "preferred"
    assert await controller._store.async_load() == {}
    assert controller.session.stopped.is_set()


@pytest.mark.asyncio
async def test_partial_selection_failure_rolls_back_first_device(controller):
    await install_services(controller, fail_b=True)
    with pytest.raises(HomeAssistantError):
        await controller.async_prepare()
    assert controller.hass.states.get("select.a").state == "preferred"
    assert controller.state == "idle"
    assert not controller.pending_restore


@pytest.mark.asyncio
async def test_busy_and_muted_devices_cannot_arm(controller):
    await install_services(controller)
    controller.hass.states.async_set("switch.a_mute", "on")
    with pytest.raises(HomeAssistantError, match="Unmute"):
        await controller.async_prepare()
    controller.hass.states.async_set("switch.a_mute", "off")
    controller.hass.states.async_set("media_player.b", "playing")
    with pytest.raises(HomeAssistantError, match="playing media"):
        await controller.async_prepare()
    assert not controller.pending_restore


@pytest.mark.asyncio
async def test_mute_event_ends_session_and_restores_pipelines(controller):
    await install_services(controller)
    await controller.async_prepare()
    controller.hass.states.async_set("switch.a_mute", "on")
    await controller.hass.async_block_till_done()
    await controller._cleanup_task
    assert controller.session.reason == "muted"
    assert controller.state == "idle"


@pytest.mark.asyncio
async def test_disconnected_device_keeps_journal_and_recovers_after_restart(controller):
    await install_services(controller)
    await controller.async_prepare()
    controller.hass.states.async_set("select.b", "unavailable")
    await controller.async_stop()
    assert controller.state == "recovery_required"
    assert "select.b" in controller.pending_restore
    await controller.async_close()
    restarted = IntercomController(controller.hass, controller.entry)
    await restarted.async_initialize()
    assert restarted.state == "recovery_required"
    controller.hass.states.async_set("select.b", "Maverick Intercom B")
    await controller.hass.async_block_till_done()
    await restarted._cleanup_task
    assert restarted.state == "idle"
    assert controller.hass.states.get("select.b").state == "preferred"
    await restarted.async_close()


@pytest.mark.asyncio
async def test_explicit_user_pipeline_change_is_preserved(controller):
    await install_services(controller)
    await controller.async_prepare()
    controller.hass.states.async_set("select.a", "Another assistant")
    await controller.hass.async_block_till_done()
    await controller._cleanup_task
    assert controller.hass.states.get("select.a").state == "Another assistant"
    assert controller.hass.states.get("select.b").state == "preferred"


@pytest.mark.asyncio
async def test_active_playback_uses_announcement_direct_stream_and_finite_stop(controller):
    calls = await install_services(controller)
    await controller.async_prepare()
    controller.session.join("a")
    controller.session.join("b")
    await controller._playback_task
    assert len(calls) == 2
    assert all(call["announce"] and call["extra"]["bypass_proxy"] for call in calls)
    assert all(call["media_content_id"].endswith("/live.wav") for call in calls)
    await controller.async_stop()
    assert len(calls) == 4
    assert all(call["media_content_id"].endswith("/stop.wav") for call in calls[2:])


@pytest.mark.asyncio
async def test_external_playback_is_preserved_while_peer_stops(controller):
    calls = await install_services(controller)
    await controller.async_prepare()
    controller.session.join("a")
    controller.session.join("b")
    await controller._playback_task
    await controller.hass.services.async_call("media_player", "play_media", {
        "entity_id": "media_player.a", "media_content_id": "http://example.test/music.wav",
    }, blocking=True, context=Context())
    await controller.hass.async_block_till_done()
    await controller._cleanup_task
    assert controller.session.reason == "playback_changed"
    stop_calls = [call for call in calls if call["media_content_id"].endswith("/stop.wav")]
    assert [call["entity_id"] for call in stop_calls] == ["media_player.b"]


@pytest.mark.asyncio
async def test_arm_timeout_automatically_restores_assist(controller, monkeypatch):
    await install_services(controller)
    monkeypatch.setattr("custom_components.maverick_intercom.controller.ARM_TIMEOUT", 0.01)
    await controller.async_prepare()
    await asyncio.wait_for(controller.session.stopped.wait(), 1)
    await controller._cleanup_task
    assert controller.session.reason == "arm_timeout"
    assert controller.state == "idle"


@pytest.mark.asyncio
async def test_repeated_hangup_does_not_interrupt_later_assist_playback(controller):
    calls = await install_services(controller)
    await controller.async_prepare()
    controller.session.join("a")
    controller.session.join("b")
    await controller._playback_task
    await controller.async_stop()
    await controller._cleanup_task
    first_count = len(calls)
    await controller.async_stop()
    assert len(calls) == first_count == 4


@pytest.mark.asyncio
async def test_cancelled_prepare_restores_already_changed_selector(controller):
    await install_services(controller)
    second_started = asyncio.Event()

    async def select(call):
        if call.data["entity_id"] == "select.b" and call.data["option"] != "preferred":
            second_started.set()
            await asyncio.Event().wait()
        controller.hass.states.async_set(call.data["entity_id"], call.data["option"], context=call.context)

    controller.hass.services.async_register("select", "select_option", select)
    task = asyncio.create_task(controller.async_prepare())
    await asyncio.wait_for(second_started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert controller.state == "idle"
    assert controller.hass.states.get("select.a").state == "preferred"
    assert not controller.pending_restore


@pytest.mark.asyncio
async def test_waiting_peer_timeout_restores_both_selectors(controller, monkeypatch):
    await install_services(controller)
    monkeypatch.setattr("custom_components.maverick_intercom.controller.JOIN_TIMEOUT", 0.01)
    await controller.async_prepare()
    controller.session.join("a")
    controller.source_joined()
    assert controller.state == "waiting"
    await asyncio.wait_for(controller.session.stopped.wait(), 1)
    await controller._cleanup_task
    assert controller.session.reason == "join_timeout"
    assert controller.state == "idle"
