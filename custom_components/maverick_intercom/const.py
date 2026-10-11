"""Constants for the stock-firmware intercom demo."""

from homeassistant.const import Platform

DOMAIN = "maverick_intercom"
PLATFORMS = [Platform.STT, Platform.BUTTON, Platform.SENSOR]
ENDPOINTS = ("a", "b")
SERVICE_PREPARE = "prepare"
SERVICE_HANG_UP = "hang_up"
STREAM_PATH = "/api/maverick_intercom/{entry_id}/{endpoint}/{token}/{kind}.wav"
ARM_TIMEOUT = 60.0
JOIN_TIMEOUT = 30.0
INPUT_TIMEOUT = 10.0
STREAM_CONNECT_TIMEOUT = 15.0
MAX_CALL_SECONDS = 600.0
