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


"""B4 parity harness tests: synthetic session -> decode -> aggregate -> parity."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.adapters.upstox.feed import ProtoFeedDecoder  # noqa: E402
from indian_quant.adapters.upstox.proto import MarketDataFeedV3_pb2 as pb2  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import replay_parity as rp  # noqa: E402


def make_session_records(tmp_path: Path, n: int = 120) -> Path:
    """Simulate a live session: encode FeedResponse frames like the wire."""
    decoder = ProtoFeedDecoder(include_market_info=False)
    lines = []
    base_ms = 1750000000000
    price = 100.0
    for i in range(n):
        resp = pb2.FeedResponse(type=pb2.live_feed, currentTs=base_ms + i * 60_000)
        feed = resp.feeds["NSE_EQ|TEST"]
        feed.requestMode = pb2.ltpc
        # engineered trend so SMA cross fires at least once
        price *= 1.004 if (i // 40) % 2 == 0 else 0.996
        feed.ltpc.ltp = round(price, 2)
        feed.ltpc.ltt = base_ms + i * 60_000
        frame = resp.SerializeToString()
        for rec in decoder.decode(frame):
            rec["last_trade_time"] = (
                __import__("datetime")
                .datetime.fromtimestamp(
                    (base_ms + i * 60_000) / 1000,
                    tz=__import__("datetime").UTC,
                )
                .isoformat()
                .replace("+00:00", "Z")
            )
            lines.append(json.dumps(rec))
    session_dir = tmp_path / "raw" / "upstox" / "feed_sessions" / "TESTSESSION"
    session_dir.mkdir(parents=True)
    (session_dir / "records.jsonl").write_text("\n".join(lines))
    return session_dir


class TestParityHarness:
    def test_load_aggregate_parity(self, tmp_path, monkeypatch):
        make_session_records(tmp_path)

        class S:
            data_root = tmp_path

        monkeypatch.setattr(rp, "__name__", rp.__name__)
        records = rp.load_session_records(S(), "TESTSESSION")
        assert len(records) > 50

        agg = rp.aggregate_ltps(records)
        assert "NSE_EQ|TEST" in agg
        closes = agg["NSE_EQ|TEST"]["ltp"]
        assert len(closes) >= 20

        report = rp.parity_report(records, key="NSE_EQ|TEST", fast=5, slow=15)
        inst = report["instruments"]["NSE_EQ|TEST"]
        assert inst["parity"] is True
        assert report["parity"] is True

    def test_signal_sequence_transitions(self):
        closes = pd.Series([50] * 20 + [100] * 20 + [150, 160, 175])
        seq = rp.signal_sequence(closes, fast=5, slow=10)
        # flat-low -> -1; sustained rally flips and stays +1
        assert seq[0] == -1 and seq[-1] == 1
        assert set(seq) <= {-1, 1}
