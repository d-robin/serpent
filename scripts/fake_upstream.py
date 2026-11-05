#!/usr/bin/env python3
"""Tiny fake SERP provider used by scripts/smoke.sh.

Behaviour:
  * any path -> 200 with a JSON echo of the query and the key it saw
  * api key "bad-key" -> 401 (exercises the invalid-key failover path)
  * /search with q=boom -> 503 (exercises refund + retry)
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("FAKE_UPSTREAM_PORT", "9911"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _key(self) -> str:
        return (
            self.headers.get("X-API-KEY")
            or parse_qs(urlparse(self.path).query).get("api_key", [""])[0]
            or ""
        )

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def _handle(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        key = self._key()
        # Always drain the body first, otherwise a keep-alive connection is
        # poisoned and the *next* request on it is parsed as garbage (400).
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if key == "bad-key":
            self._send(401, {"error": "invalid api key"})
            return
        if qs.get("q", [""])[0] == "boom":
            self._send(503, {"error": "upstream on fire"})
            return
        self._send(
            200,
            {
                "provider": "fake-serp",
                "path": parsed.path,
                "query": {k: v[0] for k, v in qs.items()},
                "body": body.decode(errors="replace"),
                "key_seen": key[:4] + "***",
            },
        )

    def log_message(self, *args) -> None:  # keep the smoke output clean
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
