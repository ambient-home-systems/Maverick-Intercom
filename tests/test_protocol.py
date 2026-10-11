import asyncio
import struct
import unittest

from maverick_intercom.protocol import Frame, HEADER, Kind, ProtocolError, control, decode_control, read_frame


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_stream_preserves_frame_boundaries(self):
        original = Frame(Kind.AUDIO, bytes(range(256)) * 2 + bytes(range(128)), 0x10203040)
        reader = asyncio.StreamReader()
        async def fragment():
            for byte in original.encode():
                reader.feed_data(bytes([byte]))
                await asyncio.sleep(0)
            reader.feed_eof()
        task = asyncio.create_task(fragment())
        self.assertEqual(await read_frame(reader), original)
        await task

    async def test_oversized_header_rejected_without_waiting_for_body(self):
        reader = asyncio.StreamReader()
        reader.feed_data(HEADER.pack(b"MVIC", 1, Kind.HELLO, 65535, 0))
        with self.assertRaises(ProtocolError):
            await asyncio.wait_for(read_frame(reader), 0.1)

    async def test_invalid_magic_version_and_kind(self):
        for magic, version, kind in [(b"NOPE", 1, 1), (b"MVIC", 2, 1), (b"MVIC", 1, 99)]:
            reader = asyncio.StreamReader()
            reader.feed_data(HEADER.pack(magic, version, kind, 1, 0))
            with self.assertRaises(ProtocolError):
                await read_frame(reader)

    def test_audio_format_and_heartbeat_length(self):
        for frame in [Frame(Kind.AUDIO, b"too short"), Frame(Kind.PING, b"unexpected"), Frame(Kind.AUDIO, b"0" * 640, -1)]:
            with self.assertRaises(ProtocolError):
                frame.encode()

    def test_control_must_be_json_object(self):
        for payload in [b"null", b"[]", b"broken", b"\xff"]:
            with self.assertRaises(ProtocolError):
                decode_control(Frame(Kind.HELLO, payload))
        self.assertEqual(decode_control(control(Kind.STATUS, {"state": "active"})), {"state": "active"})

    def test_wire_header_fixture(self):
        encoded = Frame(Kind.AUDIO, b"0" * 640, 0x10203040).encode()
        self.assertEqual(encoded[:12], bytes.fromhex("4d5649430103028010203040"))
