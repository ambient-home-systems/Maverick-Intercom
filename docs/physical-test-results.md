# Milestone 1 physical results

Status: **not run**. Two Voice Preview devices are available to the user. The cloud
environment has no connection to their microphone, speaker, or Home Assistant.

Record the following for each test session:

Preferred test path: **stock firmware with the HA intercom integration demo**.
The integration is implemented and software-tested on HA 2026.10.1; follow
[the installation guide](integration-demo.md). Record whether a session uses
this path or the optional custom firmware lab, and record the exact Home
Assistant Core version. All physical results below are still pending.

| Item | Device A | Device B |
| --- | --- | --- |
| Device name and suffix setting | Pending | Pending |
| Stock firmware version / optional experimental build | Pending | Pending |
| XMOS version | Pending | Pending |
| Assist pipeline and enabled wake words | Pending | Pending |
| Room, speaking distance, and volume | Pending | Pending |
| Wi-Fi AP and signal level | Pending | Pending |

Never enter API keys, Wi-Fi passwords, OTA passwords, or intercom tokens here.

| Check | Result | Notes / measurements |
| --- | --- | --- |
| Normal Assist before intercom | Not run | |
| Single device waits; timeout and audio forwarding behavior | Not run | Custom overlay sends no mic audio while waiting; stock pipeline may already send audio to HA |
| Stock input stream survives silence and remains active during playback | Not run | |
| Stock devices decode live WAV; both playback connections and audible speech | Not run | `active` alone is insufficient |
| Stock path restores the original Assist pipeline on all exit paths | Not run | |
| Two devices join; simultaneous speech audible | Not run | |
| Echo / double-talk at normal and high volume | Not run | |
| Ten-minute conversation; no increasing delay | Not run | |
| One-way acoustic latency ≤250 ms | Not run | Measurement method needed |
| Hardware and software mute terminate session | Not run | |
| Center-button hang-up; wake words restored | Not run | |
| Busy Assist/media rejects joining | Not run | |
| Peer loss / HA restart / Wi-Fi loss restore Assist | Not run | Also test relay restart if using the custom lab |
| Invalid certificate / token restore Assist (custom relay lab) | Not run | |
| HA reconnect during call; normal Assist resumes | Not run | |
| Timers, normal buttons, and media work afterward | Not run | |
| Timer or competing media during a call; cleanup preserves replacement playback | Not run | |
| Device restart leaves intercom off | Not run | |
| Stock firmware recovery succeeds (if custom lab firmware used) | Not run | |

The milestone is incomplete until the conversation and restoration checks pass.
Software packet timing, a successful build, or an active entity does not substitute
for hearing both devices and exercising their normal Assist behavior.
