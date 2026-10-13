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


"""Prometheus-format metrics from the metadata store.

Usage:
    python scripts/metrics.py                 # text output (scrape-ready)
    python scripts/metrics.py --serve 9108    # tiny HTTP endpoint
"""


import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config import load_settings


def _db_path(settings) -> Path:
    return Path(settings.storage.metadata_dsn.removeprefix("sqlite:///"))


def collect_metrics(settings) -> dict[str, float | int]:
    db = _db_path(settings)
    out: dict[str, float | int] = {}
    if not db.exists():
        return {"metadata_present": 0}
    con = sqlite3.connect(str(db))
    try:
        jobs_total = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        jobs_failed = con.execute("SELECT COUNT(*) FROM jobs WHERE status='FAILED'").fetchone()[0]
        runs_total = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        qr_total, qr_err = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(n_errors),0) FROM quality_reports"
        ).fetchone()
        last_job = con.execute("SELECT MAX(finished_at) FROM jobs").fetchone()[0]
        out.update(
            {
                "jobs_total": jobs_total,
                "jobs_failed": jobs_failed,
                "runs_total": runs_total,
                "quality_reports_total": qr_total,
                "quality_errors_total": int(qr_err or 0),
                "metadata_present": 1,
            }
        )
        if last_job:
            try:
                last_dt = datetime.fromisoformat(last_job)
                out["seconds_since_last_finished_job"] = max(
                    0, int((datetime.now(UTC) - last_dt).total_seconds())
                )
            except ValueError:
                pass
    finally:
        con.close()
    return out


def render(metrics: dict[str, float | int]) -> str:
    lines = ["# TYPE indian_quant_metric gauge"]
    for key, value in metrics.items():
        lines.append(f"indian_quant_{key} {value}")
    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    payload = ""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.payload.encode())

    def log_message(self, *args):  # silence
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Platform metrics exporter")
    parser.add_argument("--serve", type=int, default=None, help="port to serve on")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    metrics = collect_metrics(settings)
    MetricsHandler.payload = render(metrics)

    if args.serve:
        print(json.dumps({"serving_port": args.serve}))
        HTTPServer(("0.0.0.0", args.serve), MetricsHandler).serve_forever()
    else:
        print(MetricsHandler.payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
