#!/usr/bin/env python3
"""Validate/build firmware with isolated fake credentials; never flash devices."""

import argparse
import base64
import os
from pathlib import Path
import secrets
import subprocess
import sys
import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--device", choices=["a", "b", "both"], default="both")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / ".local/firmware-check"
    target.mkdir(parents=True, exist_ok=True)
    cert = target / "test.crt"
    if not cert.exists():
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
            "-days", "365", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(target / "test.key"), "-out", str(cert),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (target / "test.key").chmod(0o600)
    for name in ("voice-pe.yaml", "voice-pe-b.yaml"):
        text = (root / "firmware" / name).read_text()
        text = text.replace("path: components", f"path: {root / 'firmware/components'}")
        text = text.replace("../.local/server.crt", str(cert))
        (target / name).write_text(text)
    fixture = target / "secrets.yaml"
    if not fixture.exists():
        values = {
            "wifi_ssid": "build-fixture-only", "wifi_password": secrets.token_hex(16),
            "api_encryption_key": base64.b64encode(secrets.token_bytes(32)).decode(),
            "api_encryption_key_b": base64.b64encode(secrets.token_bytes(32)).decode(),
            "ota_password": secrets.token_hex(16), "ota_password_b": secrets.token_hex(16),
            "intercom_host": "localhost", "intercom_token": secrets.token_hex(32),
            "intercom_token_b": secrets.token_hex(32),
        }
        fixture.write_text("\n".join(f'{key}: "{value}"' for key, value in values.items()) + "\n")
        fixture.chmod(0o600)
    environment = dict(os.environ)
    environment["PLATFORMIO_CORE_DIR"] = str(root / ".platformio")
    environment["ESPHOME_ESP_IDF_PREFIX"] = str(root / ".local/esp-idf")
    environment["PIP_CACHE_DIR"] = str(root / ".local/pip-cache")
    environment["UV_CACHE_DIR"] = str(root / ".local/uv-cache")
    environment["IDF_COMPONENT_CACHE_PATH"] = str(root / ".local/idf-component-cache")
    # IDF's source archive has no Git metadata. Stop its revision lookup from
    # finding the enclosing project, whose HEAD may still be unborn.
    git_ceiling = str(root / ".local")
    if environment.get("GIT_CEILING_DIRECTORIES"):
        git_ceiling += os.pathsep + environment["GIT_CEILING_DIRECTORIES"]
    environment["GIT_CEILING_DIRECTORIES"] = git_ceiling
    environment["ESPHOME_BUILD_PROCESSES"] = "4"
    names = ["voice-pe.yaml", "voice-pe-b.yaml"] if args.device == "both" else ["voice-pe.yaml" if args.device == "a" else "voice-pe-b.yaml"]
    for name in names:
        action = "compile" if args.compile else "config"
        log = target / (name + "." + action + ".log")
        print(f"{action}: {name}; build fixtures only; log: {log.relative_to(root)}", flush=True)
        with log.open("w") as output:
            result = subprocess.run([
                str(root / ".venv/bin/esphome"), action, str(target / name),
            ], cwd=root, env=environment, stdout=output, stderr=subprocess.STDOUT)
        # ESPHome can echo secrets in validation errors. Keep our fixture logs redacted.
        contents = log.read_text()
        for value in yaml.safe_load(fixture.read_text()).values():
            contents = contents.replace(str(value), "<build-fixture>")
        log.write_text(contents)
        if result.returncode:
            print("Check failed; inspect the local log. No device was flashed.", file=sys.stderr)
            raise SystemExit(result.returncode)
        print(f"PASS: {name}", flush=True)


if __name__ == "__main__":
    main()
