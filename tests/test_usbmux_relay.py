import importlib.util
import socket
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELAY_PATH = ROOT / "bin" / "lib" / "usbmux-relay.py"
SPEC = importlib.util.spec_from_file_location("usbmux_relay", RELAY_PATH)
RELAY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RELAY)


class UnixEchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while data := self.request.recv(65536):
            self.request.sendall(data)


class ThreadingUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class RelayTests(unittest.TestCase):
    def test_relays_bidirectional_data(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = str(Path(directory) / "usbmuxd.sock")
            with ThreadingUnixServer(socket_path, UnixEchoHandler) as upstream:
                upstream_thread = threading.Thread(
                    target=upstream.serve_forever, daemon=True
                )
                upstream_thread.start()
                with RELAY.RelayServer(("127.0.0.1", 0), socket_path) as relay:
                    relay_thread = threading.Thread(
                        target=relay.serve_forever, daemon=True
                    )
                    relay_thread.start()
                    with socket.create_connection(relay.server_address) as client:
                        client.sendall(b"usbmux relay test")
                        client.shutdown(socket.SHUT_WR)
                        self.assertEqual(client.recv(65536), b"usbmux relay test")
                        self.assertEqual(client.recv(65536), b"")
                    relay.shutdown()
                upstream.shutdown()


if __name__ == "__main__":
    unittest.main()
