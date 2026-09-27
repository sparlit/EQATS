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


"""Portfolio backtest tests: sizing, stops, slots, clusters, costs.

Updated for next-bar execution: signals fire on day T, entries happen at open of day T+1.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.research.portfolio_backtest import (  # noqa: E402
    StrategyConfig,
    run_portfolio,
)


def make_frame(symbol: str, closes, delivs: list[float], segment="EQ", opens: list[float] | None = None):
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="B", tz="UTC")
    data = {
        "date": dates,
        "symbol": symbol,
        "segment": segment,
        "close": closes,
        "deliv_pct": delivs,
        "volume": np.full(len(closes), 500_000.0),
    }
    if opens is not None:
        data["open"] = opens
    df = pd.DataFrame(data)
    from indian_quant.features.delivery import add_features, prepare_frame

    return add_features(prepare_frame(df))


class TestPortfolioBacktest:
    def _cfg(self, **kw):
        defaults = {
            "signal": "dz_hi_up",
            "price_min": 1.0,
            "price_max": 1e9,
            "min_turnover": 0.0,
            "hold_days": 10,
            "stop_pct": 0.07,
            "max_positions": 8,
            "capital": 25_000.0,
            "risk_pct": 1.0,
            "cost_bps": 107.0,
            "cluster_entries": False,
            "use_tech_filters": False,
        }
        defaults.update(kw)
        return StrategyConfig(**defaults)

    def test_single_trade_lifecycle(self):
        # Signal fires on day 18 (deliv spike), entry at open of day 19, hold to horizon
        closes = [100.0] * 18 + [101.0] * 22
        delivs = [45.0] * 17 + [90.0] * 23
        opens = [100.0] * 18 + [100.5] * 22
        frames = [make_frame("TEST", closes, delivs, opens=opens)]
        result = run_portfolio(frames, self._cfg(hold_days=5))
        assert result.summary["n_trades"] >= 1
        trade = result.trades[0]
        assert trade.symbol == "TEST"
        assert trade.reason in ("HORIZON", "DATA_END")

    def test_stop_exit_triggers(self):
        # Signal fires, entry at open, then price drops to trigger stop
        closes = [100.0] * 18 + [101.0] * 3 + [85.0] * 20
        delivs = [45.0] * 17 + [92.0] * 24
        opens = [100.0] * 18 + [100.5] * 3 + [95.0] * 20
        frames = [make_frame("TEST", closes, delivs, opens=opens)]
        result = run_portfolio(frames, self._cfg())
        stops = [t for t in result.trades if t.reason == "STOP"]
        assert len(stops) >= 1
        assert stops[0].net_bps < -700  # 7% stop minus costs

    def test_max_positions_constraint(self):
        # three symbols fire the same day; only 2 slots allowed
        frames = []
        for sym in ("AAA", "BBB", "CCC"):
            closes = [100.0] * 18 + [110.0] * 22
            delivs = [45.0] * 17 + [95.0] * 23
            opens = [100.0] * 18 + [100.0] * 22
            f = make_frame(sym, closes, delivs, opens=opens)
            f["deliv_z"] = f["deliv_z"] + {"AAA": 3, "BBB": 2, "CCC": 1}[sym]  # deterministic priority
            frames.append(f)
        result = run_portfolio(frames, self._cfg(max_positions=2))
        entered = {t.symbol for t in result.trades}
        assert len(entered) <= 2

    def test_cluster_first_fire_only(self):
        # delivery >=60 with rising price fires spike_70 on consecutive days;
        # cluster_entries must produce exactly ONE entry
        closes = list(np.linspace(100, 130, 45))
        delivs = [80.0] * 45
        frames = [make_frame("TEST", closes, delivs)]
        cfg = StrategyConfig(
            signal="spike_70",
            price_min=1.0,
            price_max=1e9,
            min_turnover=0.0,
            hold_days=3,
            cluster_entries=True,
            use_tech_filters=False,
        )
        result = run_portfolio(frames, cfg)
        assert result.summary["n_trades"] == 1

    def test_costs_applied_per_round_trip(self):
        closes = [100.0] * 18 + [101.0] * 22
        delivs = [45.0] * 17 + [90.0] * 23
        opens = [100.0] * 18 + [100.5] * 22
        frames = [make_frame("TEST", closes, delivs, opens=opens)]
        r_free = run_portfolio(frames, self._cfg(cost_bps=0.0, hold_days=5))
        r_cost = run_portfolio(frames, self._cfg(cost_bps=107.0, hold_days=5))
        if r_free.trades and r_cost.trades:
            g_free = r_free.trades[0].net_bps
            g_cost = r_cost.trades[0].net_bps
            assert g_free == pytest.approx(g_cost + 107.0, abs=2)
