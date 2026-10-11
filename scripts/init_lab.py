#!/usr/bin/env python3
"""Create local TLS material and device credentials. Never overwrite existing files."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", default="localhost", help="LAN DNS name used by endpoints")
    parser.add_argument("--ip", help="Optional LAN IP to include in the certificate")
    args = parser.parse_args()
    if not args.hostname or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in args.hostname):
        parser.error("hostname must be a DNS name")
    san = f"DNS:{args.hostname},DNS:localhost,IP:127.0.0.1"
    if args.ip:
        san += f",IP:{ipaddress.ip_address(args.ip)}"
    target = Path(".local")
    target.mkdir(mode=0o700, exist_ok=True)
    paths = [target / name for name in ("server.crt", "server.key", "relay.json")]
    if any(path.exists() for path in paths):
        parser.error("local credentials already exist; use them or explicitly archive them first")
    os.umask(0o077)
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
        "-days", "365", "-subj", f"/CN={args.hostname}", "-addext", f"subjectAltName={san}",
        "-keyout", str(paths[1]), "-out", str(paths[0]),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    paths[2].write_text(json.dumps({"devices": {name: secrets.token_hex(32) for name in ("voice-a", "voice-b")}}, indent=2) + "\n")
    print("Created local TLS certificate and two device credentials under .local/ (values not printed).")


if __name__ == "__main__":
    main()
