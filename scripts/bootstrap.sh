#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PIP_CACHE_DIR="$PWD/.local/pip-cache"
export UV_CACHE_DIR="$PWD/.local/uv-cache"
export IDF_COMPONENT_CACHE_PATH="$PWD/.local/idf-component-cache"
export PLATFORMIO_CORE_DIR="$PWD/.platformio"
export ESPHOME_ESP_IDF_PREFIX="$PWD/.local/esp-idf"
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-dev.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
