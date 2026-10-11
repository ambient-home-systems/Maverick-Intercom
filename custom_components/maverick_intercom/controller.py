"""HA services and reversible pipeline selection for a single demo pair."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
import logging
import time
from urllib.parse import urlsplit

from homeassistant.components.assist_pipeline import async_get_pipelines
from homeassistant.components.assist_pipeline.pipeline import (
    async_create_default_pipeline, async_get_pipeline,
)
from homeassistant.components.assist_pipeline.const import OPTION_PREFERRED
from homeassistant.const import (
    EVENT_CALL_SERVICE, EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP,
    STATE_UNAVAILABLE, STATE_UNKNOWN,
)
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .audio import AudioSession
from .const import (
    ARM_TIMEOUT, DOMAIN, ENDPOINTS, JOIN_TIMEOUT, MAX_CALL_SECONDS,
    STREAM_CONNECT_TIMEOUT, STREAM_PATH,
)

_LOGGER = logging.getLogger(__name__)
_UNAVAILABLE = {STATE_UNAVAILABLE, STATE_UNKNOWN}


def validate_base_url(value: str) -> str:
    """Use a device-reachable HA URL, without credentials, query, or fragment."""
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https") or not parsed.hostname
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Enter the Home Assistant LAN URL, including its port")
    try:
        parsed.port
    except ValueError as err:
        raise ValueError("Invalid port") from err
    return value.rstrip("/")


class IntercomController:
    """State and resources for one pair; all operations run on HA's event loop."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.pair = entry.data["endpoints"]
        self.base_url = validate_base_url(entry.options.get("base_url", entry.data["base_url"]))
        self.provider_ids: dict[str, str] = {}
        self.session: AudioSession | None = None
        self.state = "idle"
        self.last_reason: str | None = None
        self.pending_restore: dict[str, dict[str, str]] = {}
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.restore")
        self._lock = asyncio.Lock()
        self._context = Context()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._watchdog: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._playback_task: asyncio.Task | None = None
        self._skip_stop: set[str] = set()
        self._closed = False
        self.silence_until = 0.0
        self._cleaned_session: AudioSession | None = None

    def pipeline_name(self, endpoint: str) -> str:
        return f"Maverick Intercom {endpoint.upper()}"

    @callback
    def listen(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def _background(self, coro, name: str) -> asyncio.Task:
        return self.hass.async_create_background_task(coro, f"{DOMAIN}: {name}")

    async def async_initialize(self) -> None:
        loaded = await self._store.async_load()
        self.pending_restore = loaded or {}
        watched = [entity_id for item in self.pair.values() for entity_id in item.values()]
        self._unsubs.extend((
            async_track_state_change_event(self.hass, watched, self._state_changed),
            self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._service_called),
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._ha_started),
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._ha_stop),
        ))
        await self.async_stop("startup_recovery")

    async def _ha_started(self, event: Event) -> None:
        if self.pending_restore:
            await self.async_stop("startup_recovery")

    async def _ha_stop(self, event: Event) -> None:
        await self.async_stop("home_assistant_stopped")

    def _state(self, entity_id: str):
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _UNAVAILABLE:
            raise HomeAssistantError(f"{entity_id} is unavailable")
        return state

    async def _call(self, domain: str, service: str, data: dict) -> None:
        async with asyncio.timeout(10):
            await self.hass.services.async_call(
                domain, service, data, blocking=True, context=self._context,
            )

    async def _ensure_pipelines(self) -> None:
        if set(self.provider_ids) != set(ENDPOINTS):
            raise HomeAssistantError("Intercom audio entities are still loading")
        for endpoint in ENDPOINTS:
            name = self.pipeline_name(endpoint)
            selected = self._state(self.pair[endpoint]["pipeline"]).state
            normal = next(
                (item for item in async_get_pipelines(self.hass) if item.name == selected), None,
            )
            if normal is None:
                if selected != OPTION_PREFERRED:
                    raise HomeAssistantError("The current Assist pipeline could not be resolved")
                normal = async_get_pipeline(self.hass)
            if not normal.stt_engine or normal.stt_engine in self.provider_ids.values():
                raise HomeAssistantError("Select each device's working normal Assist pipeline before preparing a call")
            if not normal.tts_engine:
                raise HomeAssistantError("Configure a working normal Assist pipeline with text-to-speech first")
            matching = [item for item in async_get_pipelines(self.hass) if item.name == name]
            if matching:
                if len(matching) != 1 or matching[0].stt_engine != self.provider_ids[endpoint]:
                    raise HomeAssistantError(f"Rename the existing unrelated pipeline named {name}")
                continue
            pipeline = await async_create_default_pipeline(
                self.hass, self.provider_ids[endpoint], normal.tts_engine, name,
            )
            if pipeline is None:
                raise HomeAssistantError("Could not create the intercom Assist pipeline")

    async def async_prepare(self) -> None:
        """Save selections before changing them. No device mic is remotely opened."""
        async with self._lock:
            if self._closed:
                raise HomeAssistantError("The integration is unloading")
            if self.session and not self.session.stopped.is_set():
                raise HomeAssistantError("A call is already prepared or running")
            if self._cleanup_task and not self._cleanup_task.done():
                raise HomeAssistantError("The previous call is still stopping")
            await self._restore()
            if self.pending_restore:
                raise HomeAssistantError("Restore the unavailable device's Assist pipeline before preparing another call")
            for config in self.pair.values():
                if self._state(config["mute"]).state != "off":
                    raise HomeAssistantError("Unmute both devices first")
                if self._state(config["satellite"]).state != "idle":
                    raise HomeAssistantError("Assist is busy; finish the conversation first")
                if self._state(config["player"]).state not in ("idle", "off"):
                    raise HomeAssistantError("A device is playing media; stop playback first")
                self._state(config["pipeline"])
            self.state = "preparing"
            self.notify()
            try:
                await self._ensure_pipelines()
                self.pending_restore = {
                    item["pipeline"]: {
                        "original": self._state(item["pipeline"]).state,
                        "intercom": self.pipeline_name(endpoint),
                    } for endpoint, item in self.pair.items()
                }
                await self._store.async_save(self.pending_restore)
                for endpoint, config in self.pair.items():
                    await self._call("select", "select_option", {
                        "entity_id": config["pipeline"], "option": self.pipeline_name(endpoint),
                    })
                self._context = Context()
                self._skip_stop.clear()
                self.session = AudioSession(self._active, self._stopped)
                self.state = "armed"
                self.last_reason = None
                self._watchdog = self._background(self._watch(self.session), "call watchdog")
            except (Exception, asyncio.CancelledError):
                await self._restore()
                self.state = "recovery_required" if self.pending_restore else "idle"
                self.last_reason = "prepare_failed"
                raise
            finally:
                self.notify()

    @callback
    def source_joined(self) -> None:
        if self.session and not self.session.active:
            self.state = "waiting"
            self.notify()

    @callback
    def _active(self) -> None:
        self.state = "connecting"
        self.notify()
        self._playback_task = self._background(self._start_playback(self.session), "start playback")

    async def _start_playback(self, session: AudioSession) -> None:
        try:
            await asyncio.gather(*(
                self._call("media_player", "play_media", {
                    "entity_id": self.pair[endpoint]["player"],
                    "media_content_id": self.base_url + STREAM_PATH.format(
                        entry_id=self.entry.entry_id, endpoint=endpoint,
                        token=session.endpoints[endpoint].token, kind="live",
                    ),
                    "media_content_type": "audio/wav",
                    "announce": True,
                    "extra": {"bypass_proxy": True},
                }) for endpoint in ENDPOINTS
            ))
        except asyncio.CancelledError:
            raise
        except Exception:
            session.stop("playback_failed")

    @callback
    def output_connected(self, session: AudioSession) -> None:
        if session is self.session and all(item.output_connected for item in session.endpoints.values()):
            self.state = "active"
            self.notify()

    @callback
    def _stopped(self, reason: str) -> None:
        self.last_reason = reason
        self.state = "stopping"
        self.notify()
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = self._background(self.async_stop(reason), "call cleanup")

    async def _watch(self, session: AudioSession) -> None:
        while not session.stopped.is_set():
            now = time.monotonic()
            if session.first_join is None and now - session.created >= ARM_TIMEOUT:
                session.stop("arm_timeout")
            elif not session.active and session.first_join and now - session.first_join >= JOIN_TIMEOUT:
                session.stop("join_timeout")
            elif session.activated:
                if now - session.activated >= MAX_CALL_SECONDS:
                    session.stop("duration_limit")
                elif now - session.activated >= STREAM_CONNECT_TIMEOUT and not all(
                    item.output_connected for item in session.endpoints.values()
                ):
                    session.stop("playback_connection_timeout")
            try:
                await asyncio.wait_for(session.stopped.wait(), timeout=0.5)
            except TimeoutError:
                pass

    async def _restore(self) -> None:
        for entity_id, saved in list(self.pending_restore.items()):
            current = self.hass.states.get(entity_id)
            if current is None or current.state in _UNAVAILABLE:
                continue
            if current.state == saved["intercom"]:
                try:
                    await self._call("select", "select_option", {
                        "entity_id": entity_id, "option": saved["original"],
                    })
                except Exception:
                    _LOGGER.warning("Assist pipeline restoration pending for %s", entity_id)
                    continue
                restored = self.hass.states.get(entity_id)
                if restored is None or restored.state != saved["original"]:
                    continue
            # Preserve an explicit user change to another normal pipeline.
            self.pending_restore.pop(entity_id)
            await self._store.async_save(self.pending_restore)

    async def async_stop(self, reason: str = "hang_up") -> None:
        async with self._lock:
            session = self.session
            needs_cleanup = session is not None and session is not self._cleaned_session
            if session and not session.stopped.is_set():
                session.stop(reason)
            self.last_reason = session.reason if session else self.last_reason
            for task in (self._watchdog, self._playback_task):
                if task and task is not asyncio.current_task() and not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            if needs_cleanup and session.activated:
                self.silence_until = time.monotonic() + 30
                for endpoint, config in self.pair.items():
                    if endpoint in self._skip_stop:
                        continue
                    try:
                        # HA's media_stop does not target the stock announcement
                        # pipeline. Replace our announcement with a finite silent
                        # WAV through the supported play_media action instead.
                        await self._call("media_player", "play_media", {
                            "entity_id": config["player"],
                            "media_content_id": self.base_url + STREAM_PATH.format(
                                entry_id=self.entry.entry_id, endpoint=endpoint,
                                token=session.endpoints[endpoint].token, kind="stop",
                            ),
                            "media_content_type": "audio/wav", "announce": True,
                            "extra": {"bypass_proxy": True},
                        })
                    except Exception:
                        _LOGGER.warning("Intercom playback stop could not reach device %s", endpoint.upper())
            await self._restore()
            if needs_cleanup:
                self._cleaned_session = session
            self.state = "recovery_required" if self.pending_restore else "idle"
            self.notify()

    @callback
    def _state_changed(self, event: Event) -> None:
        if self._closed:
            return
        if self.state == "recovery_required":
            if not self._cleanup_task or self._cleanup_task.done():
                self._cleanup_task = self._background(self.async_stop("recovery_retry"), "restore retry")
            return
        session = self.session
        if session is None or session.stopped.is_set():
            return
        entity_id = event.data["entity_id"]
        new = event.data["new_state"]
        if new is None or new.state in _UNAVAILABLE:
            session.stop("device_unavailable")
            return
        for endpoint, config in self.pair.items():
            if entity_id == config["mute"] and new.state != "off":
                session.stop("muted")
            elif entity_id == config["pipeline"] and new.state != self.pipeline_name(endpoint):
                session.stop("pipeline_changed")

    @callback
    def _service_called(self, event: Event) -> None:
        session = self.session
        if session is None or session.stopped.is_set() or event.context.id == self._context.id:
            return
        if event.data.get("domain") != "media_player":
            return
        if event.data.get("service") not in {"play_media", "media_stop", "media_pause", "media_play", "media_next_track"}:
            return
        data = event.data.get("service_data", {})
        entity_ids = data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        for endpoint, config in self.pair.items():
            if config["player"] in entity_ids or entity_ids == ["all"]:
                self._skip_stop.add(endpoint)
                session.stop("playback_changed")

    @callback
    def output_lost(self, session: AudioSession, endpoint: str) -> None:
        if not session.stopped.is_set():
            self._skip_stop.add(endpoint)
            session.stop("playback_disconnected")

    async def async_close(self) -> None:
        self._closed = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self.async_stop("integration_unloaded")
        if self._cleanup_task and self._cleanup_task is not asyncio.current_task():
            await self._cleanup_task
