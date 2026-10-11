"""Audio behavior with real asynchronous producers and consumers."""

import asyncio
import struct

import pytest

from custom_components.maverick_intercom.audio import (
    AudioSession, FRAME_BYTES, QUEUE_FRAMES, SILENCE, wav_header,
)


def session():
    return AudioSession(lambda: None, lambda reason: None)


@pytest.mark.asyncio
async def test_no_peer_audio_before_both_join_and_full_duplex_fragmentation():
    call = session()
    assert call.join("a")
    call.feed("a", b"X" * FRAME_BYTES)
    assert call.endpoints["b"].queue.empty()
    assert call.join("b")
    a = b"A" * FRAME_BYTES
    b = b"B" * FRAME_BYTES
    call.feed("a", a[:217])
    call.feed("b", b)
    assert call.endpoints["b"].queue.empty()
    call.feed("a", a[217:])
    assert call.endpoints["a"].queue.get_nowait() == b
    assert call.endpoints["b"].queue.get_nowait() == a
    assert not call.join("a")


@pytest.mark.asyncio
async def test_overload_keeps_latest_audio_and_bounds_memory():
    call = session()
    call.join("a")
    call.join("b")
    call.feed("a", b"".join(bytes([index]) * FRAME_BYTES for index in range(12)))
    target = call.endpoints["b"]
    assert target.queue.qsize() == QUEUE_FRAMES
    assert target.dropped_frames == 7
    assert [target.queue.get_nowait()[0] for _ in range(QUEUE_FRAMES)] == list(range(7, 12))
    assert len(call.endpoints["a"].pending) < FRAME_BYTES


@pytest.mark.asyncio
async def test_output_fills_silence_and_stops_without_replaying_buffers():
    call = session()
    call.join("a")
    call.join("b")
    output = call.output("a")
    assert await anext(output) == SILENCE
    call.feed("b", b"B" * FRAME_BYTES)
    assert await anext(output) == b"B" * FRAME_BYTES
    call.feed("b", b"C" * FRAME_BYTES)
    call.stop("hang_up")
    with pytest.raises(StopAsyncIteration):
        await anext(output)
    assert call.endpoints["a"].queue.empty()
    assert not call.join("a")


@pytest.mark.asyncio
async def test_one_microphone_eof_ends_both_pending_readers():
    call = session()
    gate = asyncio.Event()

    async def first():
        yield SILENCE
        await gate.wait()

    async def second():
        yield SILENCE

    tasks = [asyncio.create_task(call.consume("a", first(), 1)),
             asyncio.create_task(call.consume("b", second(), 1))]
    await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert call.reason == "microphone_ended"


@pytest.mark.asyncio
async def test_missing_input_and_cancellation_end_session():
    call = session()

    async def blocked():
        await asyncio.Event().wait()
        yield b""

    await call.consume("a", blocked(), 0.03)
    assert call.reason == "microphone_timeout"
    call = session()
    task = asyncio.create_task(call.consume("a", blocked(), 1))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert call.reason == "microphone_cancelled"


def test_wav_stream_and_finite_stop_clip_have_correct_format():
    streamed = struct.unpack("<4sI4s4sIHHIIHH4sI", wav_header())
    assert streamed == (b"RIFF", 0xFFFFFFFF, b"WAVE", b"fmt ", 16, 1, 1,
                        16000, 32000, 2, 16, b"data", 0xFFFFFFFF)
    finite = wav_header(FRAME_BYTES)
    assert struct.unpack_from("<I", finite, 4)[0] == FRAME_BYTES + 36
    assert struct.unpack_from("<I", finite, 40)[0] == FRAME_BYTES
