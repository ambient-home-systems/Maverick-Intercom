# Stock Voice Preview intercom demo

This custom Home Assistant integration uses **stock Voice Preview firmware**.
It provides an explicit two-device call demo. The software is tested against
Home Assistant Core **2026.10.1** and the source interfaces in Voice Preview
**26.9.0**. Audio quality and actual device playback are not physically validated.

## Install with HACS

[![Add repository to Home Assistant through HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ambient-home-systems&repository=Maverick-Intercom&category=integration)

1. Have **HACS** installed in Home Assistant, then click the repository button
   above. Add `ambient-home-systems/Maverick-Intercom` with category **Integration**.
   If the button does not work, use HACS → Custom repositories and enter
   `https://github.com/ambient-home-systems/Maverick-Intercom` with that category.
2. Find **Maverick Intercom** in HACS and download it. Adding the repository alone
   does not install the integration.
3. Restart Home Assistant, then use the setup button below or go to Settings →
   Devices & services → Add integration and search for **Maverick Intercom**.
4. Follow the device and LAN URL selection instructions in steps 4–5 below.

[![Add Maverick Intercom to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=maverick_intercom)

## Install manually and configure

1. Download the GitHub repository using **Code → Download ZIP**, use the supplied
   `maverick-intercom-demo.zip`, or generate the install archive with
   `python3 scripts/package_integration.py` from this repository.
2. Extract its `custom_components/maverick_intercom` folder into your Home
   Assistant configuration directory. The resulting path must be
   `/config/custom_components/maverick_intercom/manifest.json` on HA OS.
3. Restart Home Assistant. Open **Settings → Devices & services → Add integration**
   and search for **Maverick Intercom**. If it is missing, refresh the browser and
   check that the folder is at the path above, then check the HA logs.
4. Choose four existing ESPHome entities for device A: its **Assist satellite**,
   **Media Player**, first **Assistant** selector, and **Mute** switch. Choose the
   corresponding four entities from device B. Use each device's normal Media
   Player, rather than its Sendspin group player. Choose **Mute**, rather than
   Disable physical controls or Wake sound.
5. Enter your **Home Assistant LAN URL**, including the port if needed, such as
   `http://192.168.1.20:8123`. Both devices must be able to reach it. This is your
   home HA address. HTTPS requires device-compatible certificate trust. The
   integration's options let you change this address later.

The integration uses the existing ESPHome connections and credentials. There is
no device firmware upload, standalone relay process, API-key entry, or separate
add-on to install for this demo. Existing normal Assist must work on both devices,
with a working speech-output provider configured in their normal pipeline.

## Make the first call

1. In the Maverick Intercom device page, press **Prepare call**. Both devices must
   be idle and unmuted. The integration creates **Maverick Intercom A** and
   **Maverick Intercom B** Assist pipelines using its own audio providers, saves
   your current selections, and selects those pipelines. Wait for **Call status**
   to show `armed`.
2. Within 60 seconds, press the existing center button on device A. Status becomes
   `waiting`. Press device B's center button within 30 seconds of A joining.
3. Status becomes `connecting` while the devices fetch audio, then `active` when
   both HTTP playback connections are established. Try speaking in each
   direction, then simultaneously. The stock listening indicator remains in use.
4. Press either device's center button again, enable either device's Mute switch,
   or press **Hang up** in Home Assistant. The integration ends both directions,
   replaces its playback with a finite silent clip, and restores the previous
   Assist selections. Verify your normal wake words and Assist afterward.

`active` establishes connections, not that the speakers are audible. That is the
first physical test. This demo ends a call after ten minutes, or on missing
microphone data, playback disconnect, or device loss. It does not auto-answer or
reconnect. Ordinary Assist commands are unavailable while its input pipeline is
carrying the call. Device A may already send microphone audio to HA while waiting;
audio is forwarded to the peer only after both devices join.

You can also call these actions from Developer Tools → Actions or a dashboard:

```yaml
action: maverick_intercom.prepare
data: {}
```

```yaml
action: maverick_intercom.hang_up
data: {}
```

The integration adds two audio-provider entities, **Prepare call**, **Hang up**,
and **Call status**. The status attributes show joined endpoints, playback
connections, input-byte counts, dropped frames, the end reason, and pending
pipeline restoration. The demo supports one configured pair.

## Recovery and troubleshooting

If status is `recovery_required`, a device's Assistant selector was unavailable
when restoration ran. Reconnect the device; restoration retries on entity updates.
Press **Hang up** to retry manually. A saved restoration record survives HA
restarts. Calls themselves do not resume after a restart. An explicit user change
to a different pipeline is preserved during cleanup.

If `connecting` ends with `playback_connection_timeout`, check the configured LAN
URL and connectivity from the devices to HA. If the devices connect but produce
no sound, keep the firmware stock and collect the HA/ESPHome playback logs and
status counters: unknown-length WAV decoding and buffering are the main remaining
hardware compatibility questions. Remove call URLs/tokens from logs before sharing.

Prepare call refuses muted/busy devices. After failed setup it rolls back any
pipeline selection already changed. If an unrelated pipeline already uses either
of the generated names, rename it first. If either configured entity is renamed or
removed, restore normal Assist selections and re-add the integration with the
current entities. When removing the integration, also remove its two generated
Assist pipelines under **Settings → Voice assistants** after confirming normal
Assist has been restored.

## What is validated and what remains

The software checks exercise integration loading, setup forms, automatic pipeline
creation, real HA speech-input pipelines carrying 20 seconds of silent samples
without the normal utterance cutoff, empty-text termination without running
intents/TTS, pipeline restoration/unload, real HTTP stream delivery, expired or
invalid tokens, bounded queues, mute/peer loss, and interrupted-session recovery.
The 20-second pipeline test delivers samples faster than real time; it proves the
pipeline control behavior and is not an acoustic or sustained device test.

The integration stores selection-recovery metadata, not audio. HA's separate
Assist debug-recording option can record pipeline audio if you have enabled it.
Input uses your existing ESPHome API connection; playback uses the configured
HTTP/HTTPS URL with random per-call, per-device capability tokens. Live tokens
expire when the call ends; the silent stop clip remains fetchable for 30 seconds.
These URLs should stay within the home network and should not be copied into
dashboards or shared logs.

Record actual results in `docs/physical-test-results.md`: ten-minute conversation,
simultaneous speech, echo, acoustic latency, hardware/software mute, center-button
hang-up, Wi-Fi/HA loss, timer interruption, and normal Assist afterward. The call
status and cloud software tests do not substitute for those checks. Alexa-style
drop-in and ringing remain later features.

## Development

The HA tests need Python 3.14.2+ and use a separate pinned environment from the
ESPHome lab. Install `uv`, then run:

```bash
bash scripts/bootstrap_ha.sh
.local/ha-venv/bin/python -m pytest tests/ha -q
.local/ha-venv/bin/python scripts/package_integration.py
```

`requirements-ha.lock` includes the tested HA runtime and component dependencies.
No third-party runtime requirement is added by the integration itself. CI runs
these checks and packages the integration as an artifact; CI has not established
any physical-device result.
