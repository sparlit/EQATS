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


"""Tests for market/sentiment.py — FII/DII parsing, breadth, news scoring."""

import pytest
from market.sentiment import FIIDIIData, _build_breadth, score_headline


class TestFIIDIIVerdict:
    def test_fii_buying(self):
        """FII net > 500 → FII_BUYING."""
        d = FIIDIIData(
            date="2025-04-01",
            fii_buy=15000,
            fii_sell=10000,
            fii_net=5000,
            dii_buy=8000,
            dii_sell=9000,
            dii_net=-1000,
            verdict="FII_BUYING",
        )
        assert d.verdict == "FII_BUYING"

    def test_fii_selling(self):
        d = FIIDIIData(
            date="2025-04-01",
            fii_buy=10000,
            fii_sell=18000,
            fii_net=-8000,
            dii_buy=8000,
            dii_sell=5000,
            dii_net=3000,
            verdict="FII_SELLING",
        )
        assert d.verdict == "FII_SELLING"


class TestBreadth:
    def test_broad_rally(self):
        b = _build_breadth(400, 100, 0)
        assert b.verdict == "BROAD_RALLY"
        assert b.ad_ratio > 2.0

    def test_broad_decline(self):
        b = _build_breadth(50, 400, 50)
        assert b.verdict == "BROAD_DECLINE"
        assert b.ad_ratio < 0.5

    def test_mixed(self):
        b = _build_breadth(250, 250, 0)
        assert b.verdict == "MIXED"


class TestNewsScoring:
    def test_bullish_headline(self):
        verdict, score = score_headline("Stock surges to record high on strong results")
        assert verdict == "BULLISH"
        assert score > 0

    def test_bearish_headline(self):
        verdict, score = score_headline("Stocks crash plunge decline amid selloff losses")
        assert verdict == "BEARISH"
        assert score < 0

    def test_neutral_headline(self):
        verdict, score = score_headline("Company announces board meeting")
        assert verdict == "NEUTRAL"
        assert score == pytest.approx(0.0, abs=0.1)
