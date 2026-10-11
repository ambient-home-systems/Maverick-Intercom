"""Exercise authenticated audio capabilities over a real HTTP connection."""

import asyncio
import time

from aiohttp import ClientSession, web
import pytest
import pytest_asyncio

from custom_components.maverick_intercom.audio import FRAME_BYTES, SILENCE, wav_header
from custom_components.maverick_intercom.http import IntercomAudioView

from test_controller import install_services


@pytest_asyncio.fixture
async def audio_server(controller):
    await install_services(controller)
    await controller.async_prepare()
    controller.session.join("a")
    controller.session.join("b")
    await controller._playback_task
    app = web.Application()
    view = IntercomAudioView(controller.hass)
    view.register(controller.hass, app, app.router)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    async with ClientSession() as client:
        yield client, f"http://127.0.0.1:{port}", controller
    await controller.async_stop()
    await runner.cleanup()


def path(controller, endpoint="a", kind="live"):
    token = controller.session.endpoints[endpoint].token
    return f"/api/maverick_intercom/demo/{endpoint}/{token}/{kind}.wav"


@pytest.mark.asyncio
async def test_bad_token_unicode_wrong_endpoint_and_seek_are_rejected(audio_server):
    client, base, controller = audio_server
    for endpoint, token in (("a", "0" * 64), ("c", "0" * 64), ("a", "é" * 64)):
        async with client.get(f"{base}/api/maverick_intercom/demo/{endpoint}/{token}/live.wav") as response:
            assert response.status == 404
    async with client.get(base + path(controller), headers={"Range": "bytes=640-"}) as response:
        assert response.status == 416


@pytest.mark.asyncio
async def test_real_http_stream_delivers_peer_pcm_and_stops(audio_server):
    client, base, controller = audio_server
    controller.session.feed("b", b"B" * FRAME_BYTES)
    response = await client.get(base + path(controller))
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert await response.content.readexactly(44) == wav_header()
    assert await response.content.readexactly(FRAME_BYTES) == b"B" * FRAME_BYTES
    assert await response.content.readexactly(FRAME_BYTES) == SILENCE
    async with client.get(base + path(controller)) as duplicate:
        assert duplicate.status == 409
    await controller.async_stop()
    await asyncio.wait_for(response.read(), 1)
    response.close()
    async with client.get(base + path(controller)) as expired:
        assert expired.status == 404


@pytest.mark.asyncio
async def test_stop_clip_is_finite_silent_and_expires(audio_server):
    client, base, controller = audio_server
    async with client.get(base + path(controller, kind="stop")) as premature:
        assert premature.status == 404
    await controller.async_stop()
    async with client.get(base + path(controller, kind="stop")) as response:
        assert response.status == 200
        assert await response.read() == wav_header(FRAME_BYTES) + SILENCE
    controller.silence_until = time.monotonic() - 1
    async with client.get(base + path(controller, kind="stop")) as expired:
        assert expired.status == 404


@pytest.mark.asyncio
async def test_player_disconnect_ends_peer_and_restores_assist(audio_server):
    client, base, controller = audio_server
    response = await client.get(base + path(controller))
    await response.content.readexactly(44 + FRAME_BYTES)
    response.close()
    await asyncio.wait_for(controller.session.stopped.wait(), 2)
    await controller._cleanup_task
    assert controller.session.reason == "playback_disconnected"
    assert controller.hass.states.get("select.b").state == "preferred"
