#!/usr/bin/env python3
"""Relay loopback TCP connections to the macOS usbmuxd Unix socket.

Wi-Fi iPhones: macOS usbmuxd lists them as ConnectionType "Network" with a
BSD sockaddr (sa_len, AF_INET6=30) that Linux libusbmuxd 2.1.0 does not
recognize, and libimobiledevice would connect to that link-local address
directly, which the Docker Desktop VM cannot reach. macOS usbmuxd will tunnel
a Connect to a Wi-Fi device just like a USB one, so the relay presents Wi-Fi
devices as tunnelled ("USB") devices. After a successful Connect the socket
carries device traffic and the relay becomes a plain byte pipe again.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import struct
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time


HEADER = struct.Struct("<IIII")  # length, version, message, tag
MAX_MESSAGE = 4 * 1024 * 1024
PLIST_VERSION, PLIST_MESSAGE = 1, 8
BINARY_RESULT, BINARY_CONNECT = 1, 2
NETWORK_ONLY_KEYS = ("NetworkAddress", "EscapedFullServiceName", "InterfaceIndex")


def tunnelled(props: dict) -> dict:
    """Present a macOS Wi-Fi device as one reached through usbmuxd Connect."""
    if props.get("ConnectionType") != "Network":
        return props
    out = {k: v for k, v in props.items() if k not in NETWORK_ONLY_KEYS}
    out["ConnectionType"] = "USB"
    out.setdefault("LocationID", 0)
    out.setdefault("ProductID", 0)
    out.setdefault("ConnectionSpeed", 480000000)
    return out


def rewrite(message: dict) -> dict:
    """Rewrite ListDevices replies and Listen 'Attached' events."""
    if isinstance(message.get("DeviceList"), list):
        devices = [d for d in message["DeviceList"] if isinstance(d, dict)]
        usb = {d.get("Properties", {}).get("SerialNumber") for d in devices
               if d.get("Properties", {}).get("ConnectionType") == "USB"}
        kept = []
        for d in devices:
            props = d.get("Properties", {})
            if props.get("ConnectionType") == "Network":
                if props.get("SerialNumber") in usb:
                    continue  # the cable is faster; list the device once
                d = {**d, "Properties": tunnelled(props)}
            kept.append(d)
        return {**message, "DeviceList": kept}
    if message.get("MessageType") == "Attached" and isinstance(message.get("Properties"), dict):
        return {**message, "Properties": tunnelled(message["Properties"])}
    return message


# --- Host device status ----------------------------------------------------
# The container sees iPhones only through usbmuxd. macOS's usbmuxd sometimes
# stops listing a Wi-Fi iPhone that is still on the network (Finder and
# CoreDevice still see it). Compare usbmuxd's list with iPhones announcing
# Wi-Fi sync over Bonjour and write the result where SideLoader can read it.
SERVICE = "_apple-mobdev2._tcp"
MAC = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")


def usbmux_list(unix_socket_path: str) -> list[dict]:
    """Ask macOS usbmuxd for its current device list."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(unix_socket_path)
        body = plistlib.dumps({"MessageType": "ListDevices", "ProgName": "sideloader-status",
                               "ClientVersionString": "sideloader"})
        sock.sendall(HEADER.pack(HEADER.size + len(body), PLIST_VERSION, PLIST_MESSAGE, 1) + body)
        length = HEADER.unpack(_recv_exact(sock, HEADER.size))[0]
        reply = plistlib.loads(_recv_exact(sock, length - HEADER.size))
    return [d.get("Properties", {}) for d in reply.get("DeviceList", []) if isinstance(d, dict)]


def wifi_mac(props: dict) -> str:
    mac = str(props.get("EscapedFullServiceName") or "").split("@", 1)[0].lower()
    return mac if MAC.match(mac) else ""


def announced_macs(seconds: float = 3.0) -> set[str]:
    """Wi-Fi MAC addresses of iPhones announcing Wi-Fi sync (dns-sd is built in)."""
    try:
        proc = subprocess.Popen(["/usr/bin/dns-sd", "-B", SERVICE, "local."],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return set()
    time.sleep(seconds)
    proc.terminate()
    try:
        output = proc.communicate(timeout=3)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        output = proc.communicate()[0]
    macs: set[str] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 7 or parts[1] not in ("Add", "Rmv") or SERVICE not in line:
            continue
        mac = parts[-1].split("@", 1)[0].lower()
        if MAC.match(mac):
            (macs.add if parts[1] == "Add" else macs.discard)(mac)
    return macs


class HostStatus(threading.Thread):
    """Every interval, write which iPhones usbmuxd lists and which it dropped."""

    def __init__(self, unix_socket_path: str, path: str, interval: int = 30) -> None:
        super().__init__(daemon=True)
        self.unix_socket_path, self.path, self.interval = unix_socket_path, path, interval

    def _load(self) -> dict:
        try:
            data = json.loads(open(self.path, encoding="utf-8").read())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def run(self) -> None:
        known = {k: v for k, v in (self._load().get("wifi_macs") or {}).items() if MAC.match(k)}
        while True:
            try:
                listed = set()
                for props in usbmux_list(self.unix_socket_path):
                    udid = str(props.get("SerialNumber") or "")
                    if not udid:
                        continue
                    listed.add(udid.lower())
                    if wifi_mac(props):
                        known[wifi_mac(props)] = udid.lower()
                macs = announced_macs()
                status = {
                    "updated": int(time.time()),
                    "listed": sorted(listed),
                    # Announcing on Wi-Fi with a known identity, yet not listed.
                    "dropped": sorted({known[m] for m in macs if m in known} - listed),
                    # Announcing iPhones never seen through usbmuxd (identity unknown).
                    "unmatched_announced": len([m for m in macs if m not in known]),
                    "mapped": sorted(set(known.values())),
                    "wifi_macs": known,
                }
                directory = os.path.dirname(self.path)
                if os.path.isdir(directory):
                    temporary = self.path + ".tmp"
                    with open(temporary, "w", encoding="utf-8") as handle:
                        json.dump(status, handle)
                    os.replace(temporary, self.path)
            except (OSError, ValueError, struct.error, plistlib.InvalidFileException) as exc:
                print(f"Host device status failed: {exc}", file=sys.stderr, flush=True)
            time.sleep(self.interval)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


class Session:
    """One client connection; parses usbmuxd framing until a Connect succeeds."""

    def __init__(self, wifi: bool) -> None:
        self.wifi = wifi
        self.raw = threading.Event()
        self.decided = threading.Event()
        self.connect_pending = False

    @staticmethod
    def _pipe(source: socket.socket, destination: socket.socket) -> None:
        while data := source.recv(65536):
            destination.sendall(data)

    @staticmethod
    def _header(data: bytes):
        if len(data) < HEADER.size:
            return None
        length, version, message, tag = HEADER.unpack(data)
        if not HEADER.size <= length <= MAX_MESSAGE or version not in (0, 1):
            return None
        return length, version, message, tag

    def client_to_upstream(self, source: socket.socket, destination: socket.socket) -> None:
        while not self.raw.is_set():
            head = _recv_exact(source, HEADER.size)
            parsed = self._header(head)
            if parsed is None:
                destination.sendall(head)
                self.raw.set()
                break
            length, version, message, _ = parsed
            body = _recv_exact(source, length - HEADER.size)
            is_connect = version == 0 and message == BINARY_CONNECT
            if version == PLIST_VERSION and message == PLIST_MESSAGE:
                try:
                    is_connect = plistlib.loads(body).get("MessageType") == "Connect"
                except Exception:
                    pass
            if is_connect:
                self.decided.clear()
                self.connect_pending = True
            destination.sendall(head + body)
            if is_connect:
                # The client sends tunnel bytes only after usbmuxd's Result.
                self.decided.wait(60)
        self._pipe(source, destination)

    def upstream_to_client(self, source: socket.socket, destination: socket.socket) -> None:
        while not self.raw.is_set():
            head = _recv_exact(source, HEADER.size)
            parsed = self._header(head)
            if parsed is None:
                destination.sendall(head)
                self.raw.set()
                self.decided.set()
                break
            length, version, message, tag = parsed
            body = _recv_exact(source, length - HEADER.size)
            result = None
            if version == PLIST_VERSION and message == PLIST_MESSAGE:
                try:
                    obj = plistlib.loads(body)
                except Exception:
                    obj = None
                if isinstance(obj, dict):
                    if obj.get("MessageType") == "Result":
                        result = obj.get("Number")
                    elif self.wifi:
                        new = rewrite(obj)
                        if new is not obj:
                            body = plistlib.dumps(new)
                            head = HEADER.pack(HEADER.size + len(body), version, message, tag)
            elif version == 0 and message == BINARY_RESULT and len(body) >= 4:
                result = struct.unpack("<I", body[:4])[0]
            destination.sendall(head + body)
            if result is not None and self.connect_pending:
                self.connect_pending = False
                if result == 0:
                    self.raw.set()
                self.decided.set()
        self._pipe(source, destination)


class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            upstream.connect(self.server.unix_socket_path)
        except OSError as exc:
            print(f"USB relay connection failed: {exc}", file=sys.stderr, flush=True)
            return

        session = Session(getattr(self.server, "wifi", True))
        with upstream:
            client_to_upstream = threading.Thread(
                target=self._run,
                args=(session.client_to_upstream, self.request, upstream),
                daemon=True,
            )
            client_to_upstream.start()
            self._run(session.upstream_to_client, upstream, self.request)
            session.decided.set()
            client_to_upstream.join()

    @staticmethod
    def _run(step, source: socket.socket, destination: socket.socket) -> None:
        try:
            step(source, destination)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass


class RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], unix_socket_path: str, wifi: bool = True) -> None:
        self.unix_socket_path = unix_socket_path
        self.wifi = wifi
        super().__init__(address, RelayHandler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Relay loopback TCP connections to macOS usbmuxd."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27015)
    parser.add_argument("--socket", default="/var/run/usbmuxd")
    parser.add_argument("--usb-only", action="store_true",
                        help="do not expose Wi-Fi iPhones to the container")
    parser.add_argument("--status-file", default="",
                        help="write host iPhone visibility (JSON) for SideLoader")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        print("USB relay host must be loopback-only.", file=sys.stderr)
        return 2
    try:
        mode = os.stat(args.socket).st_mode
    except OSError as exc:
        print(f"USB mux socket unavailable: {exc}", file=sys.stderr)
        return 1
    if not stat.S_ISSOCK(mode):
        print(f"USB mux path is not a socket: {args.socket}", file=sys.stderr)
        return 1

    if args.status_file:
        HostStatus(args.socket, args.status_file).start()
    try:
        with RelayServer((args.host, args.port), args.socket, wifi=not args.usb_only) as server:
            print(
                f"USB relay listening on {args.host}:{args.port} -> {args.socket}"
                f"{' (USB only)' if args.usb_only else ' (USB + Wi-Fi)'}",
                flush=True,
            )
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"USB relay failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
