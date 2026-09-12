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


"""Tests for backend/scripts/snapshot_writer.py (B1 plan item)."""
import datetime
import json
import os
import sys
import tempfile
import unittest

# Allow `import scripts.snapshot_writer` when pytest runs from backend/
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.abspath(os.path.join(HERE, "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import pytest
import snapshot_writer  # noqa: E402


def _make_latest(generated_at: str, gate_pass: bool = True) -> dict:
    return {
        "generated_at": generated_at,
        "universe_size": 1,
        "gate_pass_count": 1 if gate_pass else 0,
        "stocks": [
            {
                "symbol": "RELIANCE",
                "gate_pass": gate_pass,
                "swing_score": 78.5,
                "current_price": 2900.0,
            }
        ],
    }


class TestSlotDerivation(unittest.TestCase):
    def test_am_slot(self):
        assert snapshot_writer.slot_for_generated_at("2026-07-18T03:31:00+00:00") == "am"
        assert snapshot_writer.slot_for_generated_at("2026-07-18T07:59:00+00:00") == "am"

    def test_pm_slot(self):
        assert snapshot_writer.slot_for_generated_at("2026-07-18T10:31:00+00:00") == "pm"
        assert snapshot_writer.slot_for_generated_at("2026-07-18T23:59:00+00:00") == "pm"

    def test_invalid_input_raises(self):
        with pytest.raises(ValueError):
            snapshot_writer.slot_for_generated_at("not-a-date")


class TestWriteSnapshot(unittest.TestCase):
    def test_writes_minified_file_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            latest = os.path.join(tmp, "latest_scan.json")
            snaps = os.path.join(tmp, "snapshots")
            with open(latest, "w") as f:
                json.dump(_make_latest("2026-07-18T10:31:00+00:00"), f)

            fname, _idx = snapshot_writer.write_snapshot(
                latest,
                snaps,
                slot="pm",
                generated_at_iso="2026-07-18T10:31:00+00:00",
                retention_days=90,
            )
            assert fname == "2026-07-18-pm.json"
            out = os.path.join(snaps, fname)
            assert os.path.exists(out)
            # Minified (no newlines inside the JSON object)
            with open(out) as f:
                text = f.read()
            assert "\n" not in text.strip()
            # Reload parses cleanly
            with open(out) as f:
                reloaded = json.load(f)
            assert reloaded["stocks"][0]["symbol"] == "RELIANCE"

            idx_path = os.path.join(snaps, "history_index.json")
            with open(idx_path) as f:
                index = json.load(f)
            assert len(index) == 1
            assert index[0]["file"] == fname
            assert index[0]["gate_pass_count"] == 1

    def test_overwrites_same_slot_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            latest = os.path.join(tmp, "latest_scan.json")
            snaps = os.path.join(tmp, "snapshots")
            with open(latest, "w") as f:
                json.dump(_make_latest("2026-07-18T10:31:00+00:00"), f)
            snapshot_writer.write_snapshot(
                latest, snaps, slot="pm", generated_at_iso="2026-07-18T10:31:00+00:00", retention_days=90
            )
            with open(latest, "w") as f:
                json.dump(_make_latest("2026-07-18T10:35:00+00:00"), f)
            snapshot_writer.write_snapshot(
                latest, snaps, slot="pm", generated_at_iso="2026-07-18T10:35:00+00:00", retention_days=90
            )
            files = [n for n in os.listdir(snaps) if n.endswith(".json") and n != "history_index.json"]
            assert files == ["2026-07-18-pm.json"]
            idx_path = os.path.join(snaps, "history_index.json")
            with open(idx_path) as f:
                index = json.load(f)
            assert len(index) == 1

    def test_prune_drops_older_than_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            latest = os.path.join(tmp, "latest_scan.json")
            snaps = os.path.join(tmp, "snapshots")
            os.makedirs(snaps)
            # Seed: an old snapshot (120 days ago) + a fresh one (today)
            old_iso = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=120)).strftime(
                "%Y-%m-%dT10:30:00+00:00"
            )
            new_iso = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT10:30:00+00:00")
            old_date = old_iso[:10]

            with open(os.path.join(snaps, f"{old_date}-pm.json"), "w") as f:
                json.dump(_make_latest(old_iso), f)
            with open(os.path.join(snaps, "history_index.json"), "w") as f:
                json.dump(
                    [
                        {
                            "date": old_date,
                            "slot": "pm",
                            "file": f"{old_date}-pm.json",
                            "generated_at": old_iso,
                            "universe_size": 1,
                            "gate_pass_count": 1,
                        }
                    ],
                    f,
                )

            with open(latest, "w") as f:
                json.dump(_make_latest(new_iso), f)
            snapshot_writer.write_snapshot(latest, snaps, slot="pm", generated_at_iso=new_iso, retention_days=90)

            files = [n for n in os.listdir(snaps) if n.endswith(".json") and n != "history_index.json"]
            assert f"{old_date}-pm.json" not in files
            new_date = new_iso[:10]
            assert f"{new_date}-pm.json" in files
            with open(os.path.join(snaps, "history_index.json")) as f:
                index = json.load(f)
            assert len(index) == 1
            assert index[0]["date"] == new_date


class TestCLI(unittest.TestCase):
    def test_cli_writes_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            latest = os.path.join(tmp, "latest_scan.json")
            snaps = os.path.join(tmp, "snapshots")
            with open(latest, "w") as f:
                json.dump(_make_latest("2026-07-18T03:31:00+00:00"), f)
            rc = snapshot_writer.main(
                [
                    "--latest",
                    latest,
                    "--snapshots",
                    snaps,
                    "--slot",
                    "am",
                    "--retention-days",
                    "90",
                ]
            )
            assert rc == 0
            assert os.path.exists(os.path.join(snaps, "2026-07-18-am.json"))

    def test_cli_missing_latest(self):
        rc = snapshot_writer.main(
            [
                "--latest",
                "/nonexistent/path/latest_scan.json",
                "--snapshots",
                "/tmp/whatever",
                "--slot",
                "am",
            ]
        )
        assert rc == 1


if __name__ == "__main__":
    unittest.main()
