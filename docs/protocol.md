# Experimental audio protocol v1

One server-authenticated TLS 1.2+ TCP connection per device. Verify the certificate
chain and host name; device tokens travel only after the TLS handshake. The server
configures exactly two device IDs, each with a private token. There is no room
selection, remote calling, negotiation, or auto-answer in this first prototype.

Every frame starts with a 12-byte header. All header integers are big-endian.

| Offset | Bytes | Meaning |
| --- | --- | --- |
| 0 | 4 | ASCII `MVIC` |
| 4 | 1 | Version: 1 |
| 5 | 1 | Kind |
| 6 | 2 | Body length |
| 8 | 4 | Audio sequence, uint32 |

| Kind | Direction | Body |
| --- | --- | --- |
| 1 HELLO | Device → relay | UTF-8 JSON object: `device_id`, `token` |
| 2 STATUS | Relay → device | UTF-8 JSON object: `state` (`waiting` or `active`) |
| 3 AUDIO | Either | Exactly 640 bytes of signed int16 little-endian mono PCM, 16 kHz |
| 4 PING | Device → relay | Empty |
| 5 PONG | Relay → device | Empty |

Control bodies are 1–2048 bytes. Validate the header before allocating/reading its
body. Unknown kinds/versions and unexpected messages terminate the connection.
The first device gets `waiting`; the second gets `waiting`, then both get `active`.
Only then may devices start capturing and sending audio. Silence is PCM samples,
not an end-of-stream marker. Sequence numbers advance for captured frames, including
frames dropped locally, wrap modulo 2^32, and reset for each connection. Receivers
accept forward gaps and reject repeats/backward moves.

Audio is forwarded to the other authenticated endpoint, never looped back to its
source. No microphone payloads or credentials are logged or recorded. Audio queues
are capped at five frames and drop new audio on overload; control ordering is
preserved. Frame gaps make overload visible. This is a first experiment, not an
adaptive jitter buffer or a guarantee about buffering in TCP, TLS, or the speaker.

Devices send PING at least every five seconds. The relay rejects a client idle
for fifteen seconds. Devices disconnect after fifteen seconds without a complete
server frame, thirty seconds waiting for a peer, or a transport/protocol failure.
Slow server writes time out after one second. A peer loss closes the other peer
and requires both devices to join again. No automatic reconnection is permitted.

Future codec, sample-rate, or call-control changes require a versioned protocol
change, rather than silently interpreting incompatible audio.
