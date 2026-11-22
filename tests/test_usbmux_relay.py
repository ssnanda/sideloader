import importlib.util
import plistlib
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
                        received = b""
                        while chunk := client.recv(65536):  # TCP may split it
                            received += chunk
                        self.assertEqual(received, b"usbmux relay test")
                    relay.shutdown()
                upstream.shutdown()


def mux(obj, tag=1):
    body = plistlib.dumps(obj)
    return RELAY.HEADER.pack(16 + len(body), 1, 8, tag) + body


def read_mux(sock):
    head = RELAY._recv_exact(sock, 16)
    length = RELAY.HEADER.unpack(head)[0]
    return plistlib.loads(RELAY._recv_exact(sock, length - 16))


WIFI = {"ConnectionType": "Network", "DeviceID": 409, "SerialNumber": "00008160-AAA",
        "NetworkAddress": b"\x1c\x1e" + b"\0" * 126, "InterfaceIndex": 6,
        "EscapedFullServiceName": "x@fe80::1._apple-mobdev2._tcp.local."}


class FakeMuxd(socketserver.BaseRequestHandler):
    """ListDevices -> one Wi-Fi device; Connect -> Result 0 then echo tunnel."""

    def handle(self):
        while True:
            try:
                msg = read_mux(self.request)
            except Exception:
                return
            if msg["MessageType"] == "ListDevices":
                self.request.sendall(mux({"DeviceList": [
                    {"DeviceID": 409, "MessageType": "Attached", "Properties": dict(WIFI)}]}))
            elif msg["MessageType"] == "Connect":
                self.request.sendall(mux({"MessageType": "Result", "Number": 0}))
                while data := self.request.recv(65536):
                    self.request.sendall(data)
                return


class WifiRewriteTests(unittest.TestCase):
    def test_rewrite_presents_wifi_as_tunnelled_and_dedups(self):
        usb = {"ConnectionType": "USB", "DeviceID": 3, "SerialNumber": "00008160-AAA"}
        other = dict(WIFI, SerialNumber="00008030-BBB", DeviceID=410)
        out = RELAY.rewrite({"DeviceList": [
            {"DeviceID": 3, "Properties": usb}, {"DeviceID": 409, "Properties": dict(WIFI)},
            {"DeviceID": 410, "Properties": other}]})
        props = [d["Properties"] for d in out["DeviceList"]]
        self.assertEqual([p["DeviceID"] for p in props], [3, 410])
        self.assertEqual(props[1]["ConnectionType"], "USB")
        self.assertNotIn("NetworkAddress", props[1])
        attached = RELAY.rewrite({"MessageType": "Attached", "DeviceID": 409, "Properties": dict(WIFI)})
        self.assertEqual(attached["Properties"]["ConnectionType"], "USB")

    def run_relay(self, wifi):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = str(Path(directory.name) / "usbmuxd.sock")
        upstream = ThreadingUnixServer(path, FakeMuxd)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        relay = RELAY.RelayServer(("127.0.0.1", 0), path, wifi=wifi)
        threading.Thread(target=relay.serve_forever, daemon=True).start()
        self.addCleanup(relay.server_close)
        self.addCleanup(relay.shutdown)
        return relay.server_address

    def test_list_rewritten_and_connect_becomes_raw_tunnel(self):
        address = self.run_relay(True)
        with socket.create_connection(address) as c:
            c.sendall(mux({"MessageType": "ListDevices"}))
            props = read_mux(c)["DeviceList"][0]["Properties"]
            self.assertEqual(props["ConnectionType"], "USB")
        with socket.create_connection(address) as c:
            c.sendall(mux({"MessageType": "Connect", "DeviceID": 409, "PortNumber": 32498}))
            self.assertEqual(read_mux(c)["Number"], 0)
            # Tunnel bytes that look nothing like usbmuxd framing pass untouched.
            payload = b"\x00\x00\x00\x10lockdown-bytes!!" * 3
            c.sendall(payload)
            c.shutdown(socket.SHUT_WR)
            received = b""
            while chunk := c.recv(65536):
                received += chunk
            self.assertEqual(received, payload)

    def test_usb_only_leaves_wifi_records_alone(self):
        address = self.run_relay(False)
        with socket.create_connection(address) as c:
            c.sendall(mux({"MessageType": "ListDevices"}))
            self.assertEqual(read_mux(c)["DeviceList"][0]["Properties"]["ConnectionType"], "Network")


if __name__ == "__main__":
    unittest.main()
