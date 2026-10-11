import asyncio
from contextlib import suppress
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest

from maverick_intercom.protocol import Frame, Kind, control, decode_control, read_frame
from maverick_intercom.relay import Endpoint, Relay, server_context


class RelayTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name)
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
            "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(cls.base / "key.pem"), "-out", str(cls.base / "cert.pem"),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    async def asyncSetUp(self):
        self.relay = Relay({"voice-a": "a" * 64, "voice-b": "b" * 64}, idle_timeout=2)
        self.tasks = set()
        def handle(reader, writer):
            task = asyncio.create_task(self.relay.handle(reader, writer))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        self.server = await asyncio.start_server(
            handle, "127.0.0.1", 0, ssl=server_context(self.base / "cert.pem", self.base / "key.pem"),
            ssl_handshake_timeout=1,
        )
        self.port = self.server.sockets[0].getsockname()[1]
        self.clients = []
        self.tls = ssl.create_default_context(cafile=self.base / "cert.pem")

    async def asyncTearDown(self):
        for _, writer in self.clients:
            writer.close()
        for _, writer in self.clients:
            with suppress(ConnectionError, ssl.SSLError):
                await writer.wait_closed()
        self.server.close()
        await self.server.wait_closed()
        if self.tasks:
            await asyncio.wait_for(asyncio.gather(*list(self.tasks)), 3)

    async def connect(self, name, token=None):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port, ssl=self.tls, server_hostname="localhost")
        self.clients.append((reader, writer))
        writer.write(control(Kind.HELLO, {"device_id": name, "token": token or name[-1] * 64}).encode())
        await writer.drain()
        return reader, writer

    async def state(self, reader):
        frame = await asyncio.wait_for(read_frame(reader), 1)
        self.assertEqual(frame.kind, Kind.STATUS)
        return decode_control(frame)["state"]

    async def pair(self):
        a = await self.connect("voice-a")
        self.assertEqual(await self.state(a[0]), "waiting")
        b = await self.connect("voice-b")
        self.assertEqual(await self.state(b[0]), "waiting")
        self.assertEqual(await self.state(a[0]), "active")
        self.assertEqual(await self.state(b[0]), "active")
        return a, b

    async def test_simultaneous_bit_exact_audio_both_directions(self):
        a, b = await self.pair()
        async def stream(sender, receiver, marker):
            for sequence in range(100):
                frame = Frame(Kind.AUDIO, bytes([marker, sequence]) * 320, sequence)
                sender.write(frame.encode())
                await sender.drain()
                self.assertEqual(await asyncio.wait_for(read_frame(receiver), 1), frame)
        await asyncio.gather(stream(a[1], b[0], 1), stream(b[1], a[0], 2))

    async def test_wrong_token_and_unknown_device_rejected(self):
        for name, token in [("voice-a", "wrong" * 10), ("unknown", "a" * 64), ("voice-a", "é" * 64)]:
            reader, _ = await self.connect(name, token)
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
        self.assertEqual(self.relay.endpoints, {})

    async def test_duplicate_does_not_evict_authenticated_endpoint(self):
        first = await self.connect("voice-a")
        self.assertEqual(await self.state(first[0]), "waiting")
        duplicate = await self.connect("voice-a")
        self.assertEqual(await asyncio.wait_for(duplicate[0].read(), 1), b"")
        first[1].write(Frame(Kind.PING).encode())
        await first[1].drain()
        self.assertEqual((await read_frame(first[0])).kind, Kind.PONG)

    async def test_audio_before_pair_is_rejected(self):
        reader, writer = await self.connect("voice-a")
        await self.state(reader)
        writer.write(Frame(Kind.AUDIO, b"0" * 640).encode())
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")

    async def test_peer_disconnect_ends_call_and_pair_can_be_recreated(self):
        a, b = await self.pair()
        a[1].close()
        await a[1].wait_closed()
        self.assertEqual(await asyncio.wait_for(b[0].read(), 1), b"")
        for _ in range(100):
            if not self.relay.endpoints:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(self.relay.endpoints, {})
        await self.pair()

    async def test_sequence_wrap_and_replay_rejection(self):
        a, b = await self.pair()
        for sequence in (0xFFFFFFFF, 0):
            a[1].write(Frame(Kind.AUDIO, b"0" * 640, sequence).encode())
            await a[1].drain()
            self.assertEqual((await read_frame(b[0])).sequence, sequence)
        a[1].write(Frame(Kind.AUDIO, b"0" * 640, 0).encode())
        await a[1].drain()
        self.assertEqual(await asyncio.wait_for(b[0].read(), 1), b"")

    async def test_idle_endpoint_is_removed(self):
        self.relay.idle_timeout = 0.05
        reader, _ = await self.connect("voice-a")
        await self.state(reader)
        self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")

    async def test_untrusted_certificate_and_wrong_hostname_rejected(self):
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        unexpected = []
        def rejected_handshake(_loop, context):
            # A client that deliberately rejects the certificate resets the server's
            # handshake. Keep that expected noise out of test output; fail on others.
            if not isinstance(context.get("exception"), ConnectionResetError):
                unexpected.append(context)
        loop.set_exception_handler(rejected_handshake)
        try:
            for ctx, hostname in [(ssl.create_default_context(), "localhost"), (self.tls, "wrong.example")]:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    await asyncio.open_connection("127.0.0.1", self.port, ssl=ctx, server_hostname=hostname)
                await asyncio.sleep(0.01)
            self.assertEqual(unexpected, [])
        finally:
            loop.set_exception_handler(previous)

    def test_queue_bounds_preserve_control_order(self):
        endpoint = Endpoint("test", None)
        status = control(Kind.STATUS, {"state": "active"})
        endpoint.outgoing.put_nowait(status)
        for sequence in range(100):
            endpoint.audio(Frame(Kind.AUDIO, b"0" * 640, sequence))
        self.assertEqual(endpoint.outgoing.qsize(), 5)
        self.assertEqual(endpoint.outgoing.get_nowait(), status)
        self.assertEqual(endpoint.dropped, 96)
