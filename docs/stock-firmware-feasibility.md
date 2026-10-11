# Stock Voice Preview firmware: feasibility and preferred direction

Stock firmware is the preferred product path. The custom ESPHome overlay remains
an experimental audio-path prototype; compiling it does not establish that a
firmware fork is necessary. No physical device has been flashed.

## Implemented stock-firmware experiment

The custom integration in `custom_components/maverick_intercom` implements a
streaming speech-input provider and local HTTP audio service. Home Assistant's
normal ESPHome integration remains the sole owner of the device's voice
subscription. See [the installation guide](integration-demo.md) to run the demo.

1. Save each device's normal Assist pipeline selection, then select a dedicated
   intercom pipeline. Use a separate speech-input entity per endpoint: the speech
   provider's audio method receives metadata and a stream, not a satellite ID.
2. For the first experiment, press each device's existing button to start its
   normal microphone session. Calls require explicit joins. That starts audio
   transmission to HA; gate forwarding to the peer until both endpoints join.
   The custom overlay's rule of sending no microphone audio while waiting is
   not established for this stock-pipeline approach.
3. The intercom provider consumes the incoming PCM and forwards it to the other
   endpoint's bounded audio queue. It declares
   `SpeechAudioProcessing(requires_external_vad=False, ...)`, so Home Assistant
   does not end its input stream at the first pause in speech. It does not
   transcribe the conversation or return command text to the intent stage.
4. Each device plays the opposite direction from an HTTP audio stream through its
   existing media player's announcement path, bypassing the HA media proxy.
   The demo uses streaming WAV; codec support, unknown-length
   streams, buffering, and sustained playback must be verified on actual devices.
   Use media-player playback rather than sending Assist TTS events that change
   the voice session into its response state.
5. On button hang-up, mute, cancellation, peer loss, or an explicit stop, terminate
   both audio directions, replace the owned announcement with a finite silent
   WAV, and restore the saved normal pipeline selections. Standard `media_stop`
   does not select the stock announcement pipeline. Recovery metadata survives
   HA restart and retries when unavailable devices return. Verify wake words and
   ordinary Assist afterward.

This routes input through an existing HA extension point instead of replacing
the ESPHome integration or attaching a competing voice client. The provider is
using a speech-input interface for intercom audio; this is an experimental use
of that interface. Integration loading, generated pipelines, capture across
20 seconds of audio samples including silence, empty-text termination without
intents/TTS, HTTP routing, and recovery pass tests against HA 2026.10.0.
Compatibility with physical stock devices remains unverified.

## What the source review establishes

- Stock Voice Preview config exposes microphone input to `voice_assistant` and
  speaker playback through `media_player`. Its processed microphone channel 0
  is a candidate for intercom capture. This does not prove acoustic echo handling.
- ESPHome's native voice API already transports microphone PCM. While its state
  is `STREAMING_MICROPHONE`, the firmware keeps sending audio. Home Assistant's
  end-of-speech event transitions it to stop the microphone; the stock device
  does not inherently require that event after a short utterance.
- Home Assistant's streaming speech provider has an `audio_processing` property.
  The reviewed pipeline creates its external utterance VAD only if
  `requires_external_vad` is true. A provider owning its stream termination is a
  path for sustained capture without editing firmware, verified in the real HA
  pipeline tests. The audio-sample test is accelerated; sustained wall-clock
  capture and playback on physical devices remain acceptance gates.
- Only one native API client can own the voice subscription. An add-on cannot
  independently subscribe to the microphone alongside Home Assistant's existing
  voice subscription. A speech-input integration avoids that conflict.
- Stock firmware ducks the regular media pipeline during Assist. Incoming-call
  audio must use the appropriate existing playback path, and its actual volume,
  interactions, and latency require measurement. Buffer capacity alone is not a
  measurement of playback delay.

The review used ESPHome 2026.9.1 and upstream development sources, then verified
the speech-input settings and pipeline behavior in HA 2026.10.1
and microphone/media-player configuration in Voice Preview 26.9.0. The user later
confirmed Core 2026.10.0; all 24 HA integration tests pass on that exact release,
and it is the installation minimum and pinned development baseline. Record the exact installed
versions in the physical test worksheet so results remain reproducible.

## Alternatives and maintenance

| Approach | Stock devices? | Assessment |
| --- | --- | --- |
| Announcements and normal Assist automations | Yes | Useful for paging and speech turns; no sustained full-duplex intercom provided out of the box |
| Dedicated streaming speech provider plus media-player audio | Yes, if the physical experiment passes | Preferred first experiment; maintains a HA integration and audio service, rather than a device firmware fork |
| Intercept/replace HA's native ESPHome voice handling | Yes | Possible research fallback, but private integration hooks or a protocol proxy add maintenance and can disrupt Assist ownership |
| Upstream supported audio-session/intercom APIs | Yes, once shipped in official releases | Strongest long-term interface; propose narrowly scoped upstream support if existing extension points prove insufficient |
| Existing custom ESPHome overlay | No | Retained lab prototype; requires rebuilding and checking firmware compatibility |

An add-on can host audio queues, streaming, and session state, but the HA custom
integration still needs to receive the audio through HA's voice pipeline. Installing
an add-on alone does not expose a general microphone stream on stock devices.

## Drop-in and acceptance gates

Remote initiation is a later gate. Stock devices have announcement/start-conversation
protocol support that can play an invitation and then listen. The public HA
`assist_satellite.start_conversation` action applies conversation-agent requirements;
it is not a generic intercom start action. Prove explicit two-device joins first,
then investigate a supported start path without pretending an LLM is required
for relaying audio. Drop-in must be an explicit per-device option with a call
indicator and working hardware mute.

Before treating this architecture as physically validated, demonstrate sustained capture across silence,
simultaneous playback/capture, acceptable one-way acoustic latency, double-talk,
and reliable cancellation. Run the ten-minute physical checks in
[the results worksheet](physical-test-results.md), plus a test longer than any
pipeline or transport timeout in the installed HA version. Test ordinary Assist
after all call exit paths. A shorter conversation or software-only test is
insufficient to establish a working stock-firmware intercom.

## Sources

- [Stock Voice Preview 26.9.0 configuration](https://github.com/esphome/home-assistant-voice-pe/blob/26.9.0/home-assistant-voice.yaml)
- [ESPHome 2026.9.1 voice state machine and subscription ownership](https://github.com/esphome/esphome/blob/2026.9.1/esphome/components/voice_assistant/voice_assistant.cpp)
- [Home Assistant 2026.10.0 speech-input processing settings](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/stt/models.py)
- [Home Assistant 2026.10.0 pipeline handling of external VAD](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/assist_pipeline/default_pipeline.py)
- [Home Assistant ESPHome satellite audio handling](https://github.com/home-assistant/core/blob/dev/homeassistant/components/esphome/assist_satellite.py)
- [Home Assistant start-conversation requirements](https://github.com/home-assistant/core/blob/dev/homeassistant/components/assist_satellite/entity.py)
