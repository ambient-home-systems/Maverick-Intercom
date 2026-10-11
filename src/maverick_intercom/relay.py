"""TLS-only relay for one explicitly configured pair. No audio is persisted."""

import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import hmac
import json
import logging
from pathlib import Path
import ssl

from .protocol import FRAME_BYTES, HEADER, Frame, Kind, ProtocolError, control, decode_control, read_frame

LOG = logging.getLogger(__name__)


@dataclass(eq=False)
class Endpoint:
    device_id: str
    writer: asyncio.StreamWriter
    outgoing: asyncio.Queue[Frame] = field(default_factory=lambda: asyncio.Queue(maxsize=5))
    active: bool = False
    closing: bool = False
    last_sequence: int | None = None
    received: int = 0
    dropped: int = 0

    def audio(self, frame: Frame) -> None:
        # Bound the application backlog to 100 ms. Never reorder or drop control.
        if self.outgoing.full():
            self.dropped += 1
            return
        self.outgoing.put_nowait(frame)


class Relay:
    def __init__(self, tokens: dict[str, str], *, idle_timeout: float = 15.0):
        if len(tokens) != 2 or any(
            not isinstance(name, str) or not name or len(name) > 64
            or not isinstance(token, str) or len(token) < 32
            for name, token in tokens.items()
        ):
            raise ValueError("configure exactly two device IDs with tokens of at least 32 characters")
        self.tokens = tokens
        self.endpoints: dict[str, Endpoint] = {}
        self.idle_timeout = idle_timeout

    async def _status(self, endpoint: Endpoint, state: str) -> None:
        await asyncio.wait_for(endpoint.outgoing.put(control(Kind.STATUS, {"state": state})), 1)

    async def _send(self, endpoint: Endpoint) -> None:
        while True:
            frame = await endpoint.outgoing.get()
            endpoint.writer.write(frame.encode())
            await asyncio.wait_for(endpoint.writer.drain(), 1)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        endpoint = None
        sender = None
        try:
            hello = await asyncio.wait_for(read_frame(reader), 5)
            if hello.kind != Kind.HELLO:
                raise ProtocolError("hello required")
            data = decode_control(hello)
            device_id, token = data.get("device_id"), data.get("token")
            # Tokens are ASCII so compare_digest cannot reject Unicode unexpectedly.
            if not isinstance(device_id, str) or not isinstance(token, str):
                raise ProtocolError("authentication rejected")
            expected = self.tokens.get(device_id)
            if expected is None or not hmac.compare_digest(token.encode(), expected.encode()):
                raise ProtocolError("authentication rejected")
            if device_id in self.endpoints:
                raise ProtocolError("device already connected")
            endpoint = Endpoint(device_id, writer)
            writer.transport.set_write_buffer_limits(high=2 * (HEADER.size + FRAME_BYTES), low=HEADER.size + FRAME_BYTES)
            self.endpoints[device_id] = endpoint
            sender = asyncio.create_task(self._send(endpoint))
            sender.add_done_callback(lambda task: writer.close() if not task.cancelled() else None)
            await self._status(endpoint, "waiting")
            peers = list(self.endpoints.values())
            if len(peers) == 2 and not any(peer.closing for peer in peers):
                for peer in peers:
                    await self._status(peer, "active")
                    peer.active = True
            while True:
                frame = await asyncio.wait_for(read_frame(reader), self.idle_timeout)
                if frame.kind == Kind.PING:
                    await asyncio.wait_for(endpoint.outgoing.put(Frame(Kind.PONG)), 1)
                elif frame.kind == Kind.AUDIO:
                    if not endpoint.active or endpoint.closing:
                        raise ProtocolError("audio outside active session")
                    if endpoint.last_sequence is not None:
                        delta = (frame.sequence - endpoint.last_sequence) & 0xFFFFFFFF
                        if not 0 < delta < 0x80000000:
                            raise ProtocolError("audio sequence is not increasing")
                    endpoint.last_sequence = frame.sequence
                    endpoint.received += 1
                    for peer in self.endpoints.values():
                        if peer is not endpoint and peer.active and not peer.closing:
                            peer.audio(frame)
                else:
                    raise ProtocolError("unexpected client message")
        except (ProtocolError, TimeoutError, asyncio.IncompleteReadError, ConnectionError, ssl.SSLError) as exc:
            # Never log HELLO payloads, tokens, or arbitrary client-provided values.
            LOG.info("Connection ended (%s)", type(exc).__name__)
        finally:
            if endpoint is not None:
                self.endpoints.pop(endpoint.device_id, None)
                LOG.info("Endpoint closed: received=%d dropped=%d", endpoint.received, endpoint.dropped)
                # A broken call ends both sides. No silent return to a waiting/open mic state.
                if endpoint.active:
                    for peer in list(self.endpoints.values()):
                        peer.active = False
                        peer.closing = True
                        peer.writer.close()
            if sender:
                sender.cancel()
                with suppress(asyncio.CancelledError, ConnectionError, TimeoutError, ssl.SSLError):
                    await sender
            writer.close()
            with suppress(ConnectionError, ssl.SSLError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 2)


def server_context(cert: Path, key: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


async def serve(args: argparse.Namespace) -> None:
    config = json.loads(args.config.read_text())
    relay = Relay(config["devices"])
    server = await asyncio.start_server(
        relay.handle, args.host, args.port, ssl=server_context(args.cert, args.key),
        ssl_handshake_timeout=5, limit=4096,
    )
    LOG.info("TLS relay listening on %s:%d", args.host, args.port)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", type=Path, default=Path(".local/relay.json"))
    parser.add_argument("--cert", type=Path, default=Path(".local/server.crt"))
    parser.add_argument("--key", type=Path, default=Path(".local/server.key"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
