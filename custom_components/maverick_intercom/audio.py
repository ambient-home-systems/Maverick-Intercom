"""Bounded, memory-only PCM routing, independent of Home Assistant."""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass, field
import secrets
import struct
import time

SAMPLE_RATE = 16000
FRAME_SECONDS = 0.02
FRAME_BYTES = 640
QUEUE_FRAMES = 5
SILENCE = bytes(FRAME_BYTES)


def wav_header(data_bytes: int | None = None) -> bytes:
    """Streaming mono PCM WAV; the consumer must support an unknown data length."""
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 0xFFFFFFFF if data_bytes is None else 36 + data_bytes,
        b"WAVE", b"fmt ", 16, 1, 1,
        SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16, b"data",
        0xFFFFFFFF if data_bytes is None else data_bytes,
    )


@dataclass
class EndpointAudio:
    token: str = field(default_factory=lambda: secrets.token_hex(32))
    queue: asyncio.Queue[bytes] = field(default_factory=lambda: asyncio.Queue(QUEUE_FRAMES))
    pending: bytearray = field(default_factory=bytearray)
    joined: bool = False
    output_connected: bool = False
    input_bytes: int = 0
    dropped_frames: int = 0
    played_frames: int = 0


class AudioSession:
    """One explicit two-device call. A stopped session can never be reused."""

    def __init__(
        self, on_active: Callable[[], None], on_stop: Callable[[str], None],
    ) -> None:
        self.endpoints = {key: EndpointAudio() for key in ("a", "b")}
        self.stopped = asyncio.Event()
        self.active = False
        self.reason: str | None = None
        self.created = time.monotonic()
        self.first_join: float | None = None
        self.activated: float | None = None
        self._on_active = on_active
        self._on_stop = on_stop

    def join(self, endpoint: str) -> bool:
        """Accept exactly one microphone stream per configured endpoint."""
        audio = self.endpoints[endpoint]
        if self.stopped.is_set() or audio.joined:
            return False
        audio.joined = True
        if self.first_join is None:
            self.first_join = time.monotonic()
        if all(item.joined for item in self.endpoints.values()):
            self.active = True
            self.activated = time.monotonic()
            self._on_active()
        return True

    def feed(self, endpoint: str, data: bytes) -> None:
        """Forward only after both join; discard the oldest frame on overload."""
        if not self.active or self.stopped.is_set():
            return
        if len(data) > 65536:
            self.stop("invalid_audio")
            return
        source = self.endpoints[endpoint]
        target = self.endpoints["b" if endpoint == "a" else "a"]
        source.input_bytes += len(data)
        source.pending.extend(data)
        while len(source.pending) >= FRAME_BYTES:
            frame = bytes(source.pending[:FRAME_BYTES])
            del source.pending[:FRAME_BYTES]
            if target.queue.full():
                target.queue.get_nowait()
                target.dropped_frames += 1
            target.queue.put_nowait(frame)

    def stop(self, reason: str) -> None:
        if self.stopped.is_set():
            return
        self.reason = reason
        self.active = False
        self.stopped.set()
        for audio in self.endpoints.values():
            audio.pending.clear()
            while not audio.queue.empty():
                audio.queue.get_nowait()
        self._on_stop(reason)

    async def consume(
        self, endpoint: str, stream: AsyncIterable[bytes], timeout: float,
        on_join: Callable[[], None] | None = None,
    ) -> None:
        """Read until stop, cancellation, EOF, or missing microphone data."""
        if not self.join(endpoint):
            return
        if on_join:
            on_join()
        iterator = stream.__aiter__()
        stop_task = asyncio.create_task(self.stopped.wait())
        read_task = None
        last_data = time.monotonic()
        try:
            while not self.stopped.is_set():
                read_task = asyncio.create_task(anext(iterator))
                done, _ = await asyncio.wait(
                    (read_task, stop_task), timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if self.stopped.is_set():
                    break
                if read_task not in done:
                    self.stop("microphone_timeout")
                    break
                try:
                    data = read_task.result()
                except StopAsyncIteration:
                    self.stop("microphone_ended")
                    break
                if data:
                    last_data = time.monotonic()
                    self.feed(endpoint, data)
                elif time.monotonic() - last_data >= timeout:
                    self.stop("microphone_timeout")
                    break
        except asyncio.CancelledError:
            self.stop("microphone_cancelled")
            raise
        except Exception:
            self.stop("microphone_error")
            raise
        finally:
            for task in (read_task, stop_task):
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                        await task

    async def output(self, endpoint: str) -> AsyncIterator[bytes]:
        """Pace audio, fill gaps with silence, and prevent catch-up bursts."""
        audio = self.endpoints[endpoint]
        deadline = asyncio.get_running_loop().time()
        while not self.stopped.is_set():
            delay = max(0.0, deadline - asyncio.get_running_loop().time())
            try:
                await asyncio.wait_for(self.stopped.wait(), timeout=delay)
                break
            except TimeoutError:
                pass
            if self.stopped.is_set():
                break
            frame = audio.queue.get_nowait() if not audio.queue.empty() else SILENCE
            audio.played_frames += 1
            yield frame
            now = asyncio.get_running_loop().time()
            deadline = now + FRAME_SECONDS if now - deadline > FRAME_SECONDS else deadline + FRAME_SECONDS
