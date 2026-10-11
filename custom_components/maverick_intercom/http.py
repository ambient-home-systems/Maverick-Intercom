"""Short-lived capability URLs for stock device HTTP playback."""

import asyncio
import hmac
import time

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .audio import SILENCE, wav_header
from .const import DOMAIN, STREAM_PATH


class IntercomAudioView(HomeAssistantView):
    url = STREAM_PATH
    name = "api:maverick_intercom:audio"
    requires_auth = False  # Stock media requests cannot supply HA bearer headers.

    def __init__(self, hass) -> None:
        self.hass = hass

    def _resolve(self, entry_id: str, endpoint: str, token: str):
        controller = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if not controller or not controller.session or endpoint not in ("a", "b"):
            raise web.HTTPNotFound()
        session = controller.session
        if len(token) != 64 or not hmac.compare_digest(
            session.endpoints[endpoint].token.encode(), token.encode(),
        ):
            raise web.HTTPNotFound()
        return controller, session

    async def get(self, request, entry_id: str, endpoint: str, token: str, kind: str):
        controller, session = self._resolve(entry_id, endpoint, token)
        headers = {"Content-Type": "audio/wav", "Cache-Control": "no-store"}
        if kind == "stop":
            if not session.stopped.is_set() or time.monotonic() > controller.silence_until:
                raise web.HTTPNotFound()
            return web.Response(body=wav_header(len(SILENCE)) + SILENCE, headers=headers)
        if kind != "live" or not session.active or session.stopped.is_set():
            raise web.HTTPNotFound()
        if request.headers.get("Range") not in (None, "bytes=0-"):
            raise web.HTTPRequestRangeNotSatisfiable()
        audio = session.endpoints[endpoint]
        if audio.output_connected:
            raise web.HTTPConflict()
        audio.output_connected = True
        response = web.StreamResponse(headers=headers)
        try:
            async with asyncio.timeout(2):
                await response.prepare(request)
                await response.write(wav_header())
            controller.output_connected(session)
            async for frame in session.output(endpoint):
                async with asyncio.timeout(2):
                    await response.write(frame)
            async with asyncio.timeout(2):
                await response.write_eof()
        except (ConnectionError, TimeoutError):
            controller.output_lost(session, endpoint)
        except asyncio.CancelledError:
            controller.output_lost(session, endpoint)
            raise
        finally:
            audio.output_connected = False
            controller.output_lost(session, endpoint)
        return response
