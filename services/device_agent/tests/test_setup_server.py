"""SetupServer runs on a real (loopback-only) TCP socket, bound to an
OS-assigned ephemeral port (port=0) - this is plain Python networking, not
NetworkManager/access-point/system config, so it's safe to exercise on any
OS including Windows, per this project's rules.
"""

import urllib.parse
import urllib.request
from urllib.error import HTTPError

from device_agent.network import WifiNetwork
from device_agent.setup_server import SetupServer


class FakeScanner:
    def __init__(self, networks):
        self._networks = networks

    def scan(self):
        return self._networks


def _start_server(networks):
    server = SetupServer(FakeScanner(networks), host="127.0.0.1", port=0)
    server.start()
    return server


def test_get_root_lists_scanned_networks():
    server = _start_server([WifiNetwork("HomeWifi", 80, True), WifiNetwork("OpenCafe", 40, False)])
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/") as response:
            assert response.status == 200
            body = response.read().decode("utf-8")
        assert "HomeWifi" in body
        assert "OpenCafe" in body
    finally:
        server.stop()


def test_unknown_path_returns_404():
    server = _start_server([])
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/nope")
            raise AssertionError("expected HTTPError")
        except HTTPError as exc:
            assert exc.code == 404
    finally:
        server.stop()


def test_post_connect_queues_submission_and_returns_confirmation():
    server = _start_server([])
    try:
        assert server.poll() is None

        data = urllib.parse.urlencode({"ssid": "HomeWifi", "password": "hunter2"}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{server.port}/connect", data=data, method="POST")
        with urllib.request.urlopen(request) as response:
            assert response.status == 200
            assert b"Connecting" in response.read()

        submission = server.poll()
        assert submission is not None
        assert submission.ssid == "HomeWifi"
        assert submission.password == "hunter2"
        assert server.poll() is None
    finally:
        server.stop()


def test_post_connect_without_ssid_returns_400_and_does_not_queue():
    server = _start_server([])
    try:
        data = urllib.parse.urlencode({"ssid": "", "password": "x"}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{server.port}/connect", data=data, method="POST")
        try:
            urllib.request.urlopen(request)
            raise AssertionError("expected HTTPError")
        except HTTPError as exc:
            assert exc.code == 400

        assert server.poll() is None
    finally:
        server.stop()


def test_post_connect_with_open_network_has_no_password():
    server = _start_server([])
    try:
        data = urllib.parse.urlencode({"ssid": "OpenCafe", "password": ""}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{server.port}/connect", data=data, method="POST")
        urllib.request.urlopen(request).read()

        submission = server.poll()
        assert submission.ssid == "OpenCafe"
        assert submission.password is None
    finally:
        server.stop()
