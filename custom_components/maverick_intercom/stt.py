"""Stream stock Assist audio without transcription or intent execution."""

from homeassistant.components import stt
from homeassistant.components.assist_pipeline import async_get_pipelines
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, ENDPOINTS, INPUT_TIMEOUT


async def async_setup_entry(hass, entry, async_add_entities):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(IntercomAudioProvider(controller, endpoint) for endpoint in ENDPOINTS)


class IntercomAudioProvider(stt.SpeechToTextEntity):
    _attr_has_entity_name = True

    def __init__(self, controller, endpoint: str) -> None:
        self.controller = controller
        self.endpoint = endpoint
        self._attr_name = f"Device {endpoint.upper()} audio"
        self._attr_unique_id = f"{controller.entry.entry_id}_{endpoint}_audio"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)}, name="Maverick Intercom",
            manufacturer="Maverick", model="Stock Voice Preview demo",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.controller.provider_ids[self.endpoint] = self.entity_id

    async def async_will_remove_from_hass(self) -> None:
        self.controller.provider_ids.pop(self.endpoint, None)
        await super().async_will_remove_from_hass()

    @property
    def supported_languages(self) -> list[str]:
        # We relay samples, so language does not change audio handling.
        return sorted({"en", self.hass.config.language} | {
            item.stt_language for item in async_get_pipelines(self.hass) if item.stt_language
        })

    @property
    def supported_formats(self):
        return [stt.AudioFormats.WAV]

    @property
    def supported_codecs(self):
        return [stt.AudioCodecs.PCM]

    @property
    def supported_bit_rates(self):
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self):
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self):
        return [stt.AudioChannels.CHANNEL_MONO]

    @property
    def audio_processing(self):
        # False for both preferences makes HA choose the unprocessed microphone
        # channel. Keep noise reduction enabled to use stock XMOS channel 0.
        return stt.SpeechAudioProcessing(
            requires_external_vad=False, prefers_auto_gain_enabled=False,
            prefers_noise_reduction_enabled=True,
        )

    async def async_process_audio_stream(self, metadata, stream):
        session = self.controller.session
        if session is not None and not session.stopped.is_set() and self.check_metadata(metadata):
            # Reject duplicate input without terminating an existing valid call.
            if not session.endpoints[self.endpoint].joined:
                try:
                    await session.consume(
                        self.endpoint, stream, INPUT_TIMEOUT,
                        on_join=self.controller.source_joined,
                    )
                except Exception:
                    # Audio contents and endpoint URLs never enter our logs.
                    session.stop("microphone_error")
        # Empty successful STT yields HA's stt-no-text-recognized terminal event.
        # Stock firmware ignores that error display and ends the mic via RUN_END.
        return stt.SpeechResult(text="", result=stt.SpeechResultState.SUCCESS)
