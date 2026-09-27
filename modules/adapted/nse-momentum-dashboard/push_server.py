from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
Minimal HTTPS microservice: receives browser push-subscription JSON from
the dashboard's own JS (see dashboard.py's "Enable notifications" button)
and persists it via state_db.save_push_subscription()/
delete_push_subscription().

Runs on its own port (PUSH_SERVER_PORT, default 8503) and its own TLS
context -- reusing the SAME cert/key Streamlit itself uses, read straight
out of .streamlit/config.toml so there's one cert to renew, not two.
Can't live on the dashboard's own port 8501: Streamlit has no route for a
custom POST endpoint, and while a service worker (static/sw.js) has to be
registered from the SAME origin as the page (which is why that file is
served by Streamlit's own static serving instead), a plain fetch() POST
to a DIFFERENT origin is fine as long as this sends proper CORS headers
-- which is what most of this file is for.

No auth beyond CORS -- same trust boundary as the dashboard itself
(reachable only over Tailscale), consistent with how every other service
in this app already trusts "anyone on the tailnet."
"""


import json
import os
import ssl
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer

import state_db

PORT = int(os.getenv("PUSH_SERVER_PORT", "8503"))


def _load_ssl_paths() -> tuple[str, str] | None:
    cfg_path = os.path.join(".streamlit", "config.toml")
    if not os.path.exists(cfg_path):
        return None
    with open(cfg_path, "rb") as f:
        toml_cfg = tomllib.load(f)
    server_cfg = toml_cfg.get("server", {})
    cert, key = server_cfg.get("sslCertFile"), server_cfg.get("sslKeyFile")
    return (cert, key) if cert and key else None


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        # Reflects the request's own Origin rather than "*" so this still
        # works if the dashboard is ever reached from more than one
        # hostname -- credentials aren't in play here (no cookies read),
        # so this is no looser than a wildcard would be in practice.
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        try:
            if self.path == "/subscribe":
                body = self._json_body()
                keys = body["keys"]
                state_db.save_push_subscription(body["endpoint"], keys["p256dh"], keys["auth"])
                self._respond(200, {"ok": True})
            elif self.path == "/unsubscribe":
                body = self._json_body()
                state_db.delete_push_subscription(body["endpoint"])
                self._respond(200, {"ok": True})
            else:
                self._respond(404, {"error": "not found"})
        except Exception as e:
            self._respond(400, {"error": str(e)})

    def log_message(self, fmt, *args):
        print(f"[push_server] {self.address_string()} - {fmt % args}")


def main():
    ssl_paths = _load_ssl_paths()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    if ssl_paths:
        cert, key = ssl_paths
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert, keyfile=key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        print(f"[push_server] HTTPS on :{PORT} (cert: {cert})")
    else:
        print(
            f"[push_server] WARNING: no SSL cert found in .streamlit/config.toml "
            f"-- running plain HTTP on :{PORT}. A dashboard served over HTTPS "
            f"can't fetch() plain HTTP (mixed content) -- subscribe requests "
            f"will fail in the browser until this has a cert too."
        )
    print(f"[push_server] listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
