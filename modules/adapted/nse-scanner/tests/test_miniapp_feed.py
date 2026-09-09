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


import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_miniapp_feed.py"
SPEC = importlib.util.spec_from_file_location("build_miniapp_feed", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


def write_json(root: Path, relative: str, value: dict) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value), encoding="utf-8")


class MiniAppFeedTest(unittest.TestCase):
    def test_plain_language_and_silent_terminal_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(
                root,
                "output/penny_microcap/daily.json",
                {
                    "as_of_date": "2026-08-25",
                    "candidates": [
                        {"symbol": "VISIBLE", "state": "READY", "score": 80, "close": 10},
                        {"symbol": "JBCHEPHARM", "state": "CONFIRMING", "score": 90, "close": 2400},
                        {"symbol": "PVTBANIETF", "state": "CONFIRMING", "score": 90, "close": 28},
                        {"symbol": "PHARMABEES", "state": "CONFIRMING", "score": 90, "close": 28},
                        {"symbol": "HDFCNIFIT", "state": "CONFIRMING", "score": 90, "close": 28},
                    ],
                },
            )
            write_json(
                root, "output/pine_hull_daily_run.json", {"trade_date": "2026-08-25", "created": [], "watch": []}
            )
            write_json(
                root,
                "output/v2_daily_run.json",
                {
                    "trade_date": "2026-08-25",
                    "dashboard_candidates": [
                        {"symbol": "V3TEST", "timing_state": "READY", "score": 88, "entry": 100, "stop": 95}
                    ],
                },
            )
            write_json(
                root,
                "output/old_nse_hull_daily.json",
                {
                    "as_of_date": "2026-08-25",
                    "shortlist": [{"symbol": "LADDERTEST", "hull_state": "WATCH", "discovery_score": 75, "close": 50}],
                },
            )
            registry = root / "corporate_data/normalized/security_lifecycle_events.csv"
            registry.parent.mkdir(parents=True)
            with registry.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["symbol", "terminal"])
                writer.writeheader()
                writer.writerow({"symbol": "JBCHEPHARM", "terminal": "1"})
            with patch.object(module, "ROOT", root):
                assert module.main() == 0
            feed = json.loads((root / "docs/data/feed.json").read_text(encoding="utf-8"))
            assert {row["symbol"] for row in feed["items"]} == {"VISIBLE", "V3TEST", "LADDERTEST"}
            by_symbol = {row["symbol"]: row for row in feed["items"]}
            assert by_symbol["VISIBLE"]["stage"] == "Watch for entry"
            assert by_symbol["V3TEST"]["stage"] == "Watch for entry"
            assert by_symbol["LADDERTEST"]["stage"] == "Watchlist—wait for confirmation"
            assert all(scanner["available"] for scanner in feed["scanners"])
            assert "JBCHEPHARM" not in json.dumps(feed)
            assert "PVTBANIETF" not in json.dumps(feed)
            assert "PHARMABEES" not in json.dumps(feed)
            assert "HDFCNIFIT" not in json.dumps(feed)

    def test_each_scanner_is_limited_to_25_and_ladder_requires_75(self):
        rows = [
            {
                "scanner": "penny",
                "symbol": f"P{i}",
                "stage": "Early watchlist",
                "score": i,
                "price": 10,
                "entry_low": 10,
                "entry_high": 10,
                "stop": 9,
                "target1": 11,
                "target2": 12,
            }
            for i in range(30)
        ]
        limited = module.limit_per_scanner(rows)
        assert len(limited) == 25
        assert limited[0]["symbol"] == "P29"
        ladder = module.ladder_items(
            {
                "shortlist": [
                    {"symbol": "LOW", "hull_state": "WATCH", "discovery_score": 74.99},
                    {"symbol": "SHOW", "hull_state": "WATCH", "discovery_score": 75.0},
                ]
            }
        )
        assert [row["symbol"] for row in ladder] == ["SHOW"]


if __name__ == "__main__":
    unittest.main()
