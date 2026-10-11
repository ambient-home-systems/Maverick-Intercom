#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/.local/uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.local/python"
export PIP_CACHE_DIR="$PWD/.local/pip-cache"
if [ ! -x .local/ha-venv/bin/python ]; then
  uv venv --python 3.14.2 .local/ha-venv
fi
uv pip install --python .local/ha-venv/bin/python -r requirements-ha.lock
uv pip check --python .local/ha-venv/bin/python
