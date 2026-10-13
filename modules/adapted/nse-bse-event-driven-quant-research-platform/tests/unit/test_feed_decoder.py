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


"""ProtoFeedDecoder tests: synthetic frames built with the official schema."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.adapters.upstox.feed import ProtoFeedDecoder  # noqa: E402
from indian_quant.adapters.upstox.proto import MarketDataFeedV3_pb2 as pb2  # noqa: E402


def make_market_full_frame() -> bytes:
    resp = pb2.FeedResponse(type=pb2.live_feed, currentTs=1725876633607)
    feed = resp.feeds["NSE_EQ|INE002A01018"]
    feed.requestMode = pb2.full_d5
    mf = feed.fullFeed.marketFF
    mf.ltpc.ltp = 1321.5
    mf.ltpc.ltt = 1725876600000
    mf.ltpc.ltq = 50
    mf.ltpc.cp = 1305.0
    mf.atp = 1318.25
    mf.vtt = 10_180_567
    mf.oi = 0.0
    top = mf.marketLevel.bidAskQuote.add()
    top.bidP = 1321.45
    top.bidQ = 600
    top.askP = 1321.55
    top.askQ = 50
    d = mf.marketOHLC.ohlc.add()
    d.interval = "1d"
    d.open = 1314.0
    d.high = 1328.6
    d.low = 1311.2
    d.close = 1321.5
    d.vol = 10_180_567
    return resp.SerializeToString()


def make_ltpc_frame() -> bytes:
    resp = pb2.FeedResponse(type=pb2.live_feed, currentTs=1725876633607)
    feed = resp.feeds["NSE_INDEX|Nifty 50"]
    feed.requestMode = pb2.ltpc
    feed.ltpc.ltp = 24252.15
    feed.ltpc.cp = 24231.95
    return resp.SerializeToString()


def make_greeks_frame() -> bytes:
    resp = pb2.FeedResponse(type=pb2.initial_feed, currentTs=1725876633607)
    feed = resp.feeds["NSE_FO|52101"]
    feed.requestMode = pb2.option_greeks
    fl = feed.firstLevelWithGreeks
    fl.ltpc.ltp = 141.35
    fl.firstDepth.bidP = 141.3
    fl.firstDepth.askP = 141.45
    fl.optionGreeks.delta = 0.42
    fl.optionGreeks.gamma = 0.0014
    return resp.SerializeToString()


class TestProtoFeedDecoder:
    def setup_method(self):
        self.decoder = ProtoFeedDecoder(include_market_info=False)

    def test_market_full_feed(self):
        recs = self.decoder.decode(make_market_full_frame())
        assert len(recs) == 1
        r = recs[0]
        assert r["instrument_key"] == "NSE_EQ|INE002A01018"
        assert r["feed_kind"] == "fullFeed"
        assert r["ltp"] == 1321.5
        assert r["close_prev"] == 1305.0
        assert r["volume_traded_today"] == 10_180_567
        assert r["bid_price"] == 1321.45 and r["ask_qty"] == 50
        assert r["ohlc_1d"]["high"] == 1328.6

    def test_ltpc_mode(self):
        r = self.decoder.decode(make_ltpc_frame())[0]
        assert r["feed_kind"] == "ltpc"
        assert r["ltp"] == 24252.15
        assert "bid_price" not in r

    def test_first_level_with_greeks(self):
        r = self.decoder.decode(make_greeks_frame())[0]
        assert r["feed_kind"] == "firstLevelWithGreeks"
        assert r["delta"] == 0.42 and r["gamma"] == 0.0014
        assert r["ask_price"] == 141.45

    def test_market_info_emitted_when_enabled(self):
        decoder = ProtoFeedDecoder(include_market_info=True)
        resp = pb2.FeedResponse(currentTs=1725876633607)
        resp.marketInfo.segmentStatus["CM"] = pb2.NORMAL_OPEN
        recs = decoder.decode(resp.SerializeToString())
        info = [r for r in recs if r.get("feed_type") == "market_info"]
        assert info and info[0]["market_info"]["CM"] == "NORMAL_OPEN"

    def test_empty_frame_yields_nothing(self):
        assert self.decoder.decode(pb2.FeedResponse().SerializeToString()) == []
