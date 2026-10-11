# Maverick Intercom

[![Add repository to Home Assistant through HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ambient-home-systems&repository=Maverick-Intercom&category=integration)
[![Add Maverick Intercom to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=maverick_intercom)

An experimental Home Assistant integration for a local intercom between
**two Home Assistant Voice Preview Edition devices running stock firmware**.
The demo routes live microphone audio through HA to the other device's speaker,
with explicit joins and restoration of normal Assist selections after a call.
The goal is a natural, full-duplex room-to-room conversation.

The installable demo is implemented and software-tested on Home Assistant
**2026.10.1**, using the source interfaces in Voice Preview **26.9.0**.
Actual stock-device playback, echo cancellation, and acoustic latency still need
physical testing. The earlier custom firmware and standalone relay remain optional
lab experiments. See [the architecture notes](docs/stock-firmware-feasibility.md)
for the stock approach and maintenance tradeoffs.

## Install and try the stock-firmware demo

With **HACS** installed, click the repository button above and add this repository
as an **Integration**. Download **Maverick Intercom** in HACS, restart Home
Assistant, then click the **Add integration** button above to configure it.
The repository button adds the HACS source; installation and restart are separate
steps. If needed, enter `https://github.com/ambient-home-systems/Maverick-Intercom`
under HACS → Custom repositories, with category **Integration**.

Follow [the installation and demo guide](docs/integration-demo.md) for entity
selection and the first call. For installation without HACS, download this
repository using GitHub's **Code → Download ZIP** and copy its
`custom_components/maverick_intercom` folder into your HA configuration directory.
You can also create the smaller install archive from this checkout:

```bash
python3 scripts/package_integration.py
```

Extract `.local/dist/maverick-intercom-demo.zip` into your HA configuration
directory so it contains `custom_components/maverick_intercom`. Restart HA and
add **Maverick Intercom** under Settings → Devices & services. Select the existing
Assist satellite, Media Player, Assistant selector, and Mute switch for each
device, then enter your HA LAN URL. No firmware upload or add-on is required.

Press **Prepare call** in HA, wait for `armed`, and press each device's existing
center button to join. **Hang up**, either center button, or mute ends the call
and restores the saved Assist selections. Normal Assist commands are unavailable
during the call. Ringing and Alexa-style drop-in are later features.

## Milestone 1: prove the audio path

The implementation is in progress. **No physical-device result has been claimed.**
Cloud tests cannot establish acoustic echo cancellation, audible latency, or the
restoration of a device's existing Assist behavior.

| Work | Status |
| --- | --- |
| TLS audio protocol and authenticated two-endpoint relay | Passed software tests and a running-service smoke test |
| Bounded queues, frame sequencing, disconnect handling | Passed software tests |
| Experimental Voice PE firmware overlay and ESPHome external component | Both configurations validate and full ESP32 builds pass |
| Preserve Assist outside calls in the firmware prototype | Implemented; physical validation pending |
| Stock-firmware HA integration, setup UI, call controls, streaming WAV | Implemented; 24 tests pass against real HA 2026.10.1 |
| HA pipeline lifetime, cancellation, mute, bounded audio, restoration/recovery | Passed software tests; physical validation pending |
| Real conversation, echo, simultaneous speech, latency, recovery | Pending two-device testing |
| Integration install ZIP and installation guide | Available; CI packaging configured, cloud checks run locally |
| Add-on packaging, ringing, drop-in, more than two devices | Later milestones |

Both devices explicitly join using their existing buttons after HA prepares the
call. Nothing auto-answers or reconnects. A waiting device can send microphone
audio to HA, but the integration forwards audio only after both join. Lost input
or playback ends both directions. The demo limits calls to ten minutes.

```mermaid
flowchart LR
  A[Stock Voice PE A] -->|Existing ESPHome API: microphone| HA[HA: Maverick Intercom]
  B[Stock Voice PE B] -->|Existing ESPHome API: microphone| HA
  HA -->|HTTP WAV: B's audio| A
  HA -->|HTTP WAV: A's audio| B
```

HA's existing ESPHome integration owns microphone input; the custom integration
uses its supported streaming speech-input extension point. It disables external
utterance segmentation and returns no transcript or intent. Peer playback uses
the stock announcement path, avoiding ordinary media ducking during Assist.

Audio uses 16 kHz mono PCM, 20 ms / 640-byte frames, and five-frame queues that
discard old frames on overload. Gaps produce silence. Playback URLs have random
per-call, per-device tokens and expire when the call ends. The integration stores
pipeline-recovery metadata and keeps audio in memory; HA's independent Assist
debug-recording setting can still record pipeline audio. Device, Wi-Fi, HTTP,
and speaker buffering must be measured before making any latency claim.

## Development setup

Use the existing checkout; cloud tasks are already isolated and do not need a
separate Git worktree.

The integration tests require Python 3.14.2+ for HA 2026.10.1. Install `uv`; the
bootstrap script creates a separate workspace environment with pinned dependencies:

```bash
bash scripts/bootstrap_ha.sh
.local/ha-venv/bin/python -m pytest tests/ha -q
.local/ha-venv/bin/python scripts/package_integration.py
```

These tests load the integration in real Home Assistant, create its Assist
pipelines, pass 20 seconds of audio samples without the normal utterance cutoff,
and exercise HTTP playback, cancellation, mute, and saved-selection recovery.
The audio samples are delivered faster than real time: this proves pipeline
behavior, not sustained hardware audio. `requirements-ha.lock` pins the tested
development runtime. The installed integration adds no third-party dependencies.

The optional firmware/relay lab requires Python 3.12+, OpenSSL, Git, and an
ESPHome-compatible build machine:

```bash
bash scripts/bootstrap.sh
.venv/bin/python -m unittest discover -s tests -v
g++ -std=c++17 -Wall -Wextra -Werror tests/wire_test.cpp -o .local/wire-test
.local/wire-test
.venv/bin/python scripts/check_firmware.py
# Required before using either firmware image:
.venv/bin/python scripts/check_firmware.py --compile
```

The relay has no third-party runtime dependencies. `requirements-dev.lock` pins
ESPHome 2026.9.1 and its development dependencies. Local credentials, environments,
and firmware build outputs are ignored by Git.
The build-check script keeps PlatformIO, native ESP-IDF, pip, uv, and component
caches inside the workspace, so it also works when the home directory is read-only.
It isolates Git discovery for generated files and framework archives from the
enclosing repository, allowing builds before the project's first commit.

## Optional custom-firmware lab relay

This section applies only to the earlier firmware experiment. The stock-firmware
integration above runs entirely inside Home Assistant.

Both custom-firmware devices must enable **Intercom Lab Join**. In that lab path,
a waiting device does not stream its microphone; capture starts only after both
join. The separate TLS relay verifies device tokens and certificate hostnames.

Run the relay on a machine reachable from both devices on the home LAN. The cloud
workspace validates software; it is not automatically reachable from home devices.

```bash
# Use the actual LAN hostname, and optionally its LAN IP, in the certificate.
.venv/bin/python scripts/init_lab.py --hostname intercom.example.home --ip 192.168.1.50
.venv/bin/python -m maverick_intercom.relay --host 0.0.0.0
```

The initializer creates `.local/server.crt`, `.local/server.key`, and
`.local/relay.json` without printing credentials or overwriting existing files.
Keep the private key and tokens local. The public certificate is embedded in
device firmware. Allow LAN access to TCP port 8765; do not expose this lab service
to the Internet. Certificate renewal requires updating the device trust material.

In another terminal, exercise the running relay with two reference endpoints:

```bash
.venv/bin/python scripts/smoke_test.py --host intercom.example.home --seconds 10
```

The smoke test sends synthetic PCM concurrently in both directions, checks bytes
and sequences, and reports relay transport timing. It does not exercise a physical
microphone, speaker, XMOS processing, or Assist. See [the protocol](docs/protocol.md)
and [the physical results worksheet](docs/physical-test-results.md).

## Optional experimental firmware and Assist coexistence

`firmware/voice-pe.yaml` extends the stock Voice PE 26.9.0 package, pinned to commit
`2644f4c794271d735d182ca7ebf899ed46164f4e`. `voice-pe-b.yaml` selects the second
device and its own credentials. The overlay adds a separate mixer input for
intercom playback, preserving the stock media and Assist paths.

During acquisition, it refuses a busy or muted device, records wake-word/button
state, pauses wake-word detection, and waits for the microphone to stop. During
the call, microphone capture and speaker playback run concurrently. Mute or
competing audio activity ends the call. Cleanup waits for audio release before
restoring prior wake-word and button behavior. Assist is temporarily unavailable
while the call owns its audio hardware; coexistence during a call is not a goal
of this first milestone.

The join switch and `Intercom Active` entity distinguish waiting from an active
session. The LED ring is refreshed amber while waiting and cyan while active.
Pressing the center button requests hang-up. These behaviors remain unverified
on hardware, including interactions with stock LED scripts, timers, and reconnects.

**Do not flash yet solely because the configuration validates or compiles.** First
record each device's current firmware version, name/name suffix setting, API key,
OTA password, Assist pipeline assignment, wake words, volume, and normal behavior.
Keep an independent stock firmware recovery path. Use your existing API/OTA
credentials, not the generated build-check fixtures. Start with one device and
verify normal Assist before modifying the second.

Copy `firmware/secrets.example.yaml` to ignored `firmware/secrets.yaml`. Fill Wi-Fi,
the existing API/OTA credentials for each device, the relay hostname matching the
certificate, and the corresponding token from `.local/relay.json`. Set the device
name and `name_add_mac_suffix` to match the existing device identity rather than
blindly accepting the example names. Never commit this file.

Build, inspect, and only then install deliberately:

```bash
export PLATFORMIO_CORE_DIR="$PWD/.platformio"
export ESPHOME_ESP_IDF_PREFIX="$PWD/.local/esp-idf"
export PIP_CACHE_DIR="$PWD/.local/pip-cache"
export UV_CACHE_DIR="$PWD/.local/uv-cache"
export IDF_COMPONENT_CACHE_PATH="$PWD/.local/idf-component-cache"
export GIT_CEILING_DIRECTORIES="$PWD/.local${GIT_CEILING_DIRECTORIES:+:$GIT_CEILING_DIRECTORIES}"
.venv/bin/esphome config firmware/voice-pe.yaml
.venv/bin/esphome compile firmware/voice-pe.yaml
.venv/bin/esphome compile firmware/voice-pe-b.yaml
# Upload commands intentionally omitted until the physical test preparation is complete.
```

The intercom uses the stock XMOS-processed microphone channel 0 and routes playback
through the stock I2S output. We must verify that this supplies the correct echo
reference and preserves speech during double-talk; having XMOS hardware is not
proof of usable full-duplex acoustics. The firmware does not reflash XMOS on its own.

## Physical acceptance checks

Record firmware versions, rooms, distances, volume, network conditions, and results.
Use a ten-minute conversation as the first sustained test, then repeat failures
after any buffer or audio-processing changes.

- Assist and configured wake words work before a call and after hang-up, peer loss,
  HA restart, playback disconnect, and waiting timeout. For the custom relay lab,
  also test relay restart and failed TLS/authentication.
- Both people can interrupt each other without speech disappearing or an audible
  feedback loop; test each direction separately and simultaneous speech.
- Hardware/software mute prevents streaming and ends the session; a device stays
  idle after restart until explicitly joined again.
- Center-button hang-up works; normal buttons, timers, and media work afterward.
- Busy Assist/media sessions refuse joining rather than being interrupted.
- Target one-way acoustic latency is at most 250 ms under normal LAN conditions.
  Measure with a repeatable recording method; synthetic relay timing is not this
  measurement. Log frame-drop counters and any increasing delay during the call.

Use [the physical results worksheet](docs/physical-test-results.md) to record the
stock integration demo's first-device and two-device results. Milestone 1 remains
open until those checks pass.

## Progress log

- **2026-10-10:** Selected the two Voice Preview devices as the first hardware target.
  Added a TLS-only relay, versioned PCM framing, and a stock-firmware intercom overlay.
  The user requires existing Assist functionality to remain usable. Software and
  firmware validation started; no devices have been flashed. Fifteen Python tests
  and a C++ framing test passed. A ten-second running-service smoke test passed
  with 500 bit-exact frames per direction. Both device configurations validated.
  Full compilation stopped at the cloud proxy's HTTP 403 denial of PlatformIO
  package registry access, before the ESP32 C++ compiler ran.
- **2026-10-10 (build retry):** PlatformIO registry access succeeded. Fixed the
  read-only home-directory cache failure by placing native ESP-IDF tools under
  `.local/esp-idf`. ESP-IDF 5.5.5 and its compiler/build tool archives downloaded.
  The build then stopped at the proxy's HTTP 403 denial of the required Espressif
  Python dependency constraints file. No ESP32 C++ compilation has passed yet,
  and no devices have been flashed.
- **2026-10-11:** Confirmed `dl.espressif.com` is allowed and its constraints
  download succeeds. The ESP-IDF Python dependencies installed after moving uv's
  cache into the workspace. Fixed CMake's Git revision lookup into the enclosing
  unborn repository. Component discovery now stops on a proxy HTTP 403 for
  `components-file.espressif.com`; the registry service and API hosts are also
  denied. The official installed component manager identifies all three as its
  registry endpoints. Full application compilation and physical testing remain
  pending.
- **2026-10-11 (successful build):** Verified all required domains are already
  allowed and component metadata access returns HTTP 200. Component downloads and
  CMake configuration passed. Replaced unsupported media-player helper methods
  with the current ESPHome state API in both audio-ownership checks. Both device
  configurations now compile and link successfully with ESPHome 2026.9.1 and
  ESP-IDF 5.5.5; partition-size checks pass. The generated images contain isolated
  build-fixture credentials and are not device installation images. No physical
  testing has occurred, and no further network change is currently needed.
- **2026-10-11 (architecture preference):** The user prefers stock Voice Preview
  firmware to avoid maintaining a firmware fork. Reviewed the latest stable
  Home Assistant 2026.10.1 and Voice Preview 26.9.0 sources. A streaming speech-input
  provider that manages its own stream termination, paired with stock media-player
  playback, is the preferred next feasibility experiment. Implementation and
  physical validation of that stock-firmware path remain pending; see
  [the design notes](docs/stock-firmware-feasibility.md).
- **Stock integration demo:** Implemented a custom HA integration with setup UI,
  two audio providers, automatic intercom pipelines, explicit join controls,
  bounded streaming WAV playback, and persistent restoration of prior Assist
  selections. Added an installation guide, ZIP packaging, pinned HA development
  environment, and CI checks. All 24 integration tests pass on HA 2026.10.1,
  including its real streaming pipeline and HTTP handlers. The separate 15 relay
  tests remain available. Stock-device audio and normal Assist recovery still
  require physical testing; no devices have been flashed.
- **GitHub installation:** Added Home Assistant buttons for adding the repository
  to HACS and opening the integration setup. Documented HACS installation, restart,
  and a GitHub ZIP fallback for testing with stock devices.

## Cloud build network access

The cloud configuration draft retains the working PlatformIO domains:
`api.registry.platformio.org`, `api.registry.nm1.platformio.org`,
`dl.registry.platformio.org`, and `dl.registry.nm1.platformio.org`.
`dl.espressif.com` is also allowed and its required constraints download now works.
The ESP-IDF component registry uses three separate official endpoints, verified
against the installed component manager:
`components-file.espressif.com` (metadata and archives),
`components.espressif.com` (registry service), and
`api.components.espressif.com` (canonical registry API).
All listed domains are now present in the environment's allowed domains. A live
component metadata request returned HTTP 200, the required components downloaded,
and CMake configuration passed. No further network settings change is currently
needed. TLS verification remains enabled. Check live access before treating any
historical network failure as a current blocker.

## Upstream references

- [ESPHome Voice PE firmware](https://github.com/esphome/home-assistant-voice-pe)
- [ESPHome Assist implementation](https://github.com/esphome/esphome/tree/2026.9.1/esphome/components/voice_assistant)
- [Home Assistant Assist satellite implementation](https://github.com/home-assistant/core/tree/dev/homeassistant/components/assist_satellite)

The default Assist listen/response pipeline is not a general intercom API. This
prototype carries audio separately, while retaining the stock HA connection for
device controls. An integration and add-on can follow once the audio path passes.
