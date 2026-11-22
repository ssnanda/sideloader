#!/usr/bin/env python3
"""Create or rotate the local SideLoader dashboard login."""

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 200_000
    ).hex()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    current = {}
    try:
        current = json.loads(args.path.read_text())
    except (FileNotFoundError, ValueError, TypeError):
        pass

    required = ("username", "salt", "hash", "secret")
    password = ""
    if args.reset or not all(current.get(key) for key in required):
        username = f"u-{secrets.token_hex(6)}"
        password = secrets.token_urlsafe(18)
        salt = secrets.token_hex(16)
        current = {
            "username": username,
            "salt": salt,
            "hash": password_hash(password, salt),
            "secret": secrets.token_hex(32),
        }
        args.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            args.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(descriptor, "w") as output:
            json.dump(current, output)
            output.write("\n")

    print(f"{current['username']}\t{password}")


if __name__ == "__main__":
    main()
