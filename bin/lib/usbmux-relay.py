#!/usr/bin/env python3
"""Relay loopback TCP connections to the macOS usbmuxd Unix socket."""

from __future__ import annotations

import argparse
import os
import socket
import socketserver
import stat
import sys
import threading


class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            upstream.connect(self.server.unix_socket_path)
        except OSError as exc:
            print(f"USB relay connection failed: {exc}", file=sys.stderr, flush=True)
            return

        with upstream:
            client_to_upstream = threading.Thread(
                target=self._copy,
                args=(self.request, upstream),
                daemon=True,
            )
            client_to_upstream.start()
            self._copy(upstream, self.request)
            client_to_upstream.join()

    @staticmethod
    def _copy(source: socket.socket, destination: socket.socket) -> None:
        try:
            while data := source.recv(65536):
                destination.sendall(data)
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

    def __init__(self, address: tuple[str, int], unix_socket_path: str) -> None:
        self.unix_socket_path = unix_socket_path
        super().__init__(address, RelayHandler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Relay loopback TCP connections to macOS usbmuxd."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27015)
    parser.add_argument("--socket", default="/var/run/usbmuxd")
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
        with RelayServer((args.host, args.port), args.socket) as server:
            print(
                f"USB relay listening on {args.host}:{args.port} -> {args.socket}",
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
