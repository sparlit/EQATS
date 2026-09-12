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


"""Tests for backend/scripts/send_digest.py (C3 plan item)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.abspath(os.path.join(HERE, "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import send_digest  # noqa: E402


def _make_scan(idx_pct=-3.5, passed_count=3, n=500, with_stale=False):
    stocks = []
    for i in range(passed_count):
        stocks.append(
            {
                "symbol": f"SYM{i}",
                "gate_pass": True,
                "swing_score": 80 - i,
                "current_price": 1000 + i * 10,
                "rsi14": 32,
                "target_1": 1100 + i * 10,
                "stop_loss": 950 + i * 10,
                "market_index_pct_from_ema200": idx_pct,
                "delivery_source_status": "ok",
                "surveillance_source_status": "source_failed" if with_stale else "ok",
                "holdings_source_status": "ok",
                "corporate_actions_status": "ok",
            }
        )
    return {
        "generated_at": "2026-07-18T10:31:00+00:00",
        "universe_size": n,
        "gate_pass_count": passed_count,
        "stocks": stocks,
    }


class TestBuildMessage(unittest.TestCase):
    def test_includes_top_pass_and_regime(self):
        with tempfile.TemporaryDirectory() as f:
            path = os.path.join(f, "latest.json")
            with open(path, "w") as fp:
                json.dump(_make_scan(idx_pct=-3.5, passed_count=3), fp)
            msg = send_digest.build_message(path, None)
        assert msg is not None
        assert "NSE Swing Scanner" in msg
        assert "Regime" in msg
        assert "Below 200EMA" in msg
        assert "PASS" in msg
        assert "SYM0" in msg
        assert "Top 5" in msg

    def test_no_pass_does_not_crash(self):
        # When passed_count=0 the stocks array is empty so we cannot
        # derive a regime; the message falls back to (unknown).
        with tempfile.TemporaryDirectory() as f:
            path = os.path.join(f, "latest.json")
            with open(path, "w") as fp:
                json.dump(_make_scan(idx_pct=2.0, passed_count=0), fp)
            msg = send_digest.build_message(path, None)
        assert "No names passed" in msg
        assert "(unknown)" in msg

    def test_missing_file_returns_none(self):
        assert send_digest.build_message("/nonexistent/latest.json", None) is None

    def test_stale_sources_listed(self):
        with tempfile.TemporaryDirectory() as f:
            path = os.path.join(f, "latest.json")
            with open(path, "w") as fp:
                json.dump(_make_scan(idx_pct=-1.0, passed_count=1, with_stale=True), fp)
            msg = send_digest.build_message(path, None)
        assert "Source warnings" in msg
        assert "Surveillance" in msg

    def test_coverage_line(self):
        scan = _make_scan(idx_pct=-1.0, passed_count=2)
        scan["coverage"] = {"priced": 450, "universe": 500, "rate_limited": 40, "pct": 0.9}
        with tempfile.TemporaryDirectory() as f:
            path = os.path.join(f, "latest.json")
            with open(path, "w") as fp:
                json.dump(scan, fp)
            msg = send_digest.build_message(path, None)
        assert "Coverage" in msg
        assert "450/500" in msg
        assert "rate-limited" in msg


class TestSendTelegram(unittest.TestCase):
    def test_missing_secrets_skips_soft(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            ok, info = send_digest.send_telegram("hello")
        assert not ok
        assert "not set" in info

    def test_http_error_is_soft(self):
        env = {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "1"}
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("urllib.request.urlopen") as u:
            u.side_effect = __import__("urllib.error").error.HTTPError(
                "http://x", 400, "Bad Request", {}, __import__("io").BytesIO(b"oops")
            )
            ok, info = send_digest.send_telegram("hello")
        assert not ok
        assert "HTTPError" in info


if __name__ == "__main__":
    unittest.main()
