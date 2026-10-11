#!/usr/bin/env python3
"""Exercise a running TLS relay with two paced, simultaneous PCM reference endpoints."""

import argparse
import asyncio
import json
import math
from pathlib import Path
import ssl
import time

from maverick_intercom.protocol import Frame, Kind, control, decode_control, read_frame


async def run(args):
    config = json.loads(args.config.read_text())
    if len(config["devices"]) != 2:
        raise ValueError("smoke test requires exactly two endpoints")
    tls = ssl.create_default_context(cafile=args.cert)
    endpoints = []
    frames = math.ceil(args.seconds / 0.02)
    stamps = [{}, {}]
    latencies = [[], []]
    try:
        for device_id, token in config["devices"].items():
            reader, writer = await asyncio.open_connection(args.host, args.port, ssl=tls, server_hostname=args.host)
            endpoints.append((reader, writer))
            writer.write(control(Kind.HELLO, {"device_id": device_id, "token": token}).encode())
            await writer.drain()
            status = await asyncio.wait_for(read_frame(reader), 5)
            if decode_control(status).get("state") != "waiting":
                raise RuntimeError("expected waiting status")
        for reader, _ in endpoints:
            status = await asyncio.wait_for(read_frame(reader), 5)
            if decode_control(status).get("state") != "active":
                raise RuntimeError("expected active status")
        started = time.perf_counter()
        async def send(index):
            writer = endpoints[index][1]
            for sequence in range(frames):
                await asyncio.sleep(max(0, started + sequence * 0.02 - time.perf_counter()))
                stamps[index][sequence] = time.perf_counter()
                payload = bytes([index + 1, sequence % 256]) * 320
                writer.write(Frame(Kind.AUDIO, payload, sequence).encode())
                await writer.drain()
        async def receive(index):
            source = 1 - index
            reader = endpoints[index][0]
            for sequence in range(frames):
                frame = await asyncio.wait_for(read_frame(reader), 5)
                if frame != Frame(Kind.AUDIO, bytes([source + 1, sequence % 256]) * 320, sequence):
                    raise RuntimeError("audio mismatch, gap, or unexpected control frame")
                latencies[source].append((time.perf_counter() - stamps[source][sequence]) * 1000)
        await asyncio.gather(send(0), send(1), receive(0), receive(1))
        summary = {"frames_per_direction": frames, "duration_seconds": args.seconds, "bit_exact": True,
                   "relay_transport_p95_ms": [round(sorted(values)[math.ceil(len(values) * 0.95) - 1], 3) for values in latencies],
                   "acoustic_latency_measured": False}
        print(json.dumps(summary, indent=2))
    finally:
        for _, writer in endpoints:
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for _, writer in endpoints), return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cert", type=Path, default=Path(".local/server.crt"))
    parser.add_argument("--config", type=Path, default=Path(".local/relay.json"))
    parser.add_argument("--seconds", type=float, default=5)
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600:
        parser.error("seconds must be between 0 and 3600")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
