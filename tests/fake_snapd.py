# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright 2018-2021 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License version 3 as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import socketserver
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple  # noqa
from urllib import parse

from tests import fake_servers


class _UnixHTTPServer(socketserver.UnixStreamServer):
    def get_request(self):
        request, client_address = self.socket.accept()
        # BaseHTTPRequestHandler expects a tuple with the client address at
        # index 0, so we fake one
        if len(client_address) == 0:
            client_address = (self.server_address,)
        return (request, client_address)


class FakeSnapd:
    """Simulate the snapd server."""

    @property
    def snaps_result(self):
        return self.request_handler.snaps_result

    @snaps_result.setter
    def snaps_result(self, value):
        self.request_handler.snaps_result = value

    @property
    def snap_details_func(
        self,
    ) -> Optional[Callable[[str], Tuple[int, Dict[str, Any]]]]:
        return self.request_handler.snap_details_func

    @snap_details_func.setter
    def snap_details_func(self, value):
        self.request_handler.snap_details_func = value

    @property
    def find_result(self):
        return self.request_handler.find_result

    @find_result.setter
    def find_result(self, value):
        self.request_handler.find_result = value

    def __init__(self):
        super().__init__()
        self.request_handler = _FakeSnapdRequestHandler
        self.snaps_result = []
        self.find_result = []
        self.server = None

    def start_fake_server(self, socket):
        self.server = _UnixHTTPServer(socket, self.request_handler)
        server_thread = threading.Thread(target=self.server.serve_forever)
        server_thread.start()
        return server_thread

    def stop_fake_server(self, thread):
        if self.server:
            self.server.shutdown()
            self.server.socket.close()
        thread.join()


class _FakeSnapdRequestHandler(fake_servers.BaseHTTPRequestHandler):
    snaps_result = []  # type: List[Dict[str, Any]]
    snap_details_func = None
    find_result = []  # type: List[Dict[str, Any]]
    find_exit_code = 200  # type: int
    _private_data = {"new_fake_snap_installed": False}

    def do_GET(self):
        parsed_url = parse.urlparse(self.path)
        if parsed_url.path == "/v2/snaps":
            self._handle_snaps()
        elif parsed_url.path.startswith("/v2/snaps/") and parsed_url.path.endswith(
            "file"
        ):
            self._handle_snap_file(parsed_url)
        elif parsed_url.path.startswith("/v2/snaps/"):
            self._handle_snap_details(parsed_url)
        elif parsed_url.path == "/v2/find":
            self._handle_find(parsed_url)
        else:
            self.wfile.write(parsed_url.path.encode())

    def _handle_snaps(self):
        status_code = self.find_exit_code
        params = self.snaps_result
        self.send_response(status_code)
        self.send_header("Content-Type", "text/application+json")
        self.end_headers()
        response = json.dumps({"result": params}).encode()
        self.wfile.write(response)

    def _handle_snap_file(self, parsed_url):
        self.send_response(200)
        self.send_header("Content-Length", str(len(parsed_url)))
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(parsed_url.encode())

    def _handle_snap_details(self, parsed_url):
        status_code = 404
        params = {"message": "not found"}
        type_ = "error"
        snap_name = parsed_url.path.split("/")[-1]
        details_func = self.snap_details_func
        if details_func:
            # pylint: disable-next=not-callable
            status_code, params = details_func(snap_name)  # type: ignore
        else:
            for snap in self.snaps_result:
                if snap["name"] == snap_name:
                    status_code = 200
                    type_ = "sync"
                    params = {}
                    for key in (
                        "channel",
                        "revision",
                        "confinement",
                        "id",
                        "tracking-channel",
                    ):
                        if key in snap:
                            params.update({key: snap[key]})
                    break

        self.send_response(status_code)
        self.send_header("Content-Type", "text/application+json")
        self.end_headers()
        response = json.dumps({"result": params, "type": type_}).encode()

        self.wfile.write(response)

    def _handle_find(self, parsed_url):
        query = parse.parse_qs(parsed_url.query)
        snap_name = query["name"][0]
        status_code = 404
        params = {}
        for result in self.find_result:
            if snap_name in result:
                status_code = 200
                params = result[snap_name]
                break
        if snap_name == "new-fake-snap":
            status_code = 200
            params = {"channels": {"latest/stable": {"confinement": "strict"}}}
        elif snap_name in ("core16", "core18"):
            status_code = 200
            params = {
                "channels": {
                    "latest/stable": {"confinement": "strict", "revision": "10"}
                }
            }

        self.send_response(status_code)
        self.send_header("Content-Type", "text/application+json")
        self.end_headers()
        response = json.dumps({"result": [params]}).encode()
        self.wfile.write(response)
