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
import os
import plistlib
import struct
import socket
import socketserver
import stat
import sys
import threading


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
