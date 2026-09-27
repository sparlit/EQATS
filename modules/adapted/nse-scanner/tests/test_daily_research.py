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


import numpy as np
import pandas as pd
import pytest
from daily_research.audit import audit_hull
from daily_research.features import candidate_mask, confirmed_pivot, features
from daily_research.replay import ExecutionConfig, metrics, replay


def prices(n=350):
    x = np.arange(n)
    c = 100 + 0.1 * x + 3 * np.sin(x / 9)
    return pd.DataFrame(
        {
            "trade_date": pd.bdate_range("2024-01-01", periods=n),
            "open": c - 0.2,
            "high": c + 1,
            "low": c - 1,
            "close": c,
            "volume": 50000,
            "turnover_lacs": 200,
            "delivery_pct": 20,
        }
    )


def replay_rows():
    return pd.DataFrame(
        {
            "trade_date": pd.bdate_range("2026-01-01", periods=6),
            "open": [99, 100, 104, 102, 105, 103],
            "high": [100, 104, 110, 106, 107, 105],
            "low": [98, 99, 99, 101, 104, 100],
            "close": [99, 103, 102, 105, 105, 103],
            "valid": True,
            "deteriorating": False,
            "support": 96.0,
            "atr": 3.0,
            "trigger": 100.0,
            "stop": 96.0,
            "setup": "RETEST",
            "weekly_permission": "HTF STRONG",
            "distance_ema_atr": 0.3,
            "distance_hull_atr": 0.4,
            "room_known": True,
            "room_r": 2.0,
        }
    )


def simulate(d, **kwargs):
    return replay(
        d,
        pd.Series([True] + [False] * (len(d) - 1)),
        "TEST",
        start="2026-01-01",
        end="2026-12-31",
        config=ExecutionConfig(fee_bps=0, slippage_bps=0, **kwargs),
    )


def test_prefix_invariance_and_completed_week():
    d = prices()
    # A Wednesday: this week's Friday must not leak into weekly permission.
    cutoff = next(i for i in range(310, 330) if d.trade_date.iloc[i].weekday() == 2)
    full, prefix = features(d), features(d.iloc[: cutoff + 1])
    cols = ["hull", "support", "resistance", "weekly_permission", "score", "setup", "room_r"]
    pd.testing.assert_frame_equal(full.loc[:cutoff, cols], prefix[cols])
    modified = d.copy()
    modified.loc[cutoff + 1 :, ["open", "high", "low", "close"]] *= 3
    pd.testing.assert_frame_equal(full.loc[:cutoff, cols], features(modified).loc[:cutoff, cols])


def test_pivot_becomes_available_only_on_confirmation():
    result = confirmed_pivot(pd.Series([5, 4, 1, 4, 5, 6]), 2, low=True)
    assert result.iloc[:4].isna().all()
    assert result.iloc[4] == 1


def test_delivery_missing_is_diagnostic_except_penny():
    a = features(prices())
    b = features(prices().drop(columns="delivery_pct"))
    pd.testing.assert_series_equal(candidate_mask(a, "V3", "progressive"), candidate_mask(b, "V3", "progressive"))
    assert b.delivery20.isna().all()
    assert not candidate_mask(b, "Penny", "progressive").any()


def test_weekly_hybrid_not_faked_from_short_history():
    d = features(prices())
    assert not d.weekly_hull_available.any()
    assert d.weekly_permission.iloc[0] == "DATA UNAVAILABLE"


def test_next_session_fill_and_partial_accounting():
    d = replay_rows()
    d.loc[3, "high"] = 113
    result = simulate(d)
    t = result["trades"][0]
    assert t["entry_date"] == "2026-01-02"
    assert t["signal_date"] == "2026-01-01"
    assert t["t1_hit"]
    assert t["t2_hit"]
    assert t["net_r"] == pytest.approx(0.4 * 1.5 + 0.6 * 3)


def test_stop_first_on_ambiguous_day():
    d = replay_rows()
    d.loc[2, ["low", "high"]] = [95, 120]
    t = simulate(d)["trades"][0]
    assert t["exit_reason"] == "STOP"
    assert t["net_r"] == -1
    assert not t["t1_hit"]


def test_gap_stop_executes_at_open():
    d = replay_rows()
    d.loc[2, ["open", "low"]] = [94, 93]
    t = simulate(d)["trades"][0]
    assert t["exit_price"] == 94
    assert t["net_r"] == -1.5


def test_entry_bar_stop_is_not_erased_as_cancelled_setup():
    d = replay_rows()
    d.loc[1, "low"] = 95
    t = simulate(d)["trades"][0]
    assert t["entry_date"] == t["exit_date"]
    assert t["net_r"] == -1


def test_gap_above_entry_cap_does_not_fill():
    d = replay_rows().iloc[:2].copy()
    d.loc[1, ["open", "high", "low", "close"]] = [105, 107, 104, 106]
    result = simulate(d)
    assert not result["open"]
    assert not result["trades"]


def test_missing_session_freezes_open_trade():
    d = replay_rows().drop(index=2).reset_index(drop=True)
    result = replay(
        d,
        pd.Series([True, False, False, False, False]),
        "TEST",
        start="2026-01-01",
        end="2026-01-31",
        config=ExecutionConfig(fee_bps=0, slippage_bps=0),
        session_calendar=pd.bdate_range("2026-01-01", periods=6).strftime("%Y-%m-%d").tolist(),
    )
    assert result["open"][0]["status"] == "REVIEW"
    assert not result["trades"]


def test_costs_reduce_net_results():
    d = replay_rows()
    d.loc[3, "high"] = 114
    free = simulate(d)["trades"][0]["net_r"]
    paid = replay(
        d, pd.Series([True, False, False, False, False, False]), "TEST", start="2026-01-01", end="2026-01-31"
    )["trades"][0]
    assert paid["net_r"] < free
    assert paid["fees"] > 0


def test_unknown_resistance_not_a_pass():
    d = features(prices())
    d["room_known"] = False
    assert not candidate_mask(d, "Hull").any()


def test_small_sample_uncertainty_and_no_fake_portfolio_drawdown():
    result = metrics([{"net_r": 1}, {"net_r": -1}])
    assert result["win_rate_pct"] == 50
    assert result["win_rate_95pct_interval"][0] < 15
    assert result["expectancy"] == 0
    assert result["portfolio_max_drawdown"] is None
    assert metrics([])["win_rate_pct"] is None


def test_locked_bar_preserves_pending_trend_exit():
    d = replay_rows()
    d.loc[2, ["open", "high", "low", "close"]] = [101, 103, 100, 102]
    d.loc[2, "deteriorating"] = True
    d.loc[3, ["open", "high", "low", "close"]] = 102
    result = simulate(d, trail=True)
    assert result["trades"][0]["exit_date"] == "2026-01-07"
    assert result["trades"][0]["exit_reason"] == "TREND_EXIT"


def test_recorded_audit_preserves_losses_and_missing_marks():
    state = {
        "capital_base": 300000,
        "last_run": "2026-01-05",
        "positions": [
            {
                "trade_id": "a",
                "symbol": "TEST",
                "state": "CLOSED",
                "entry_date": "2026-01-01",
                "exit_date": "2026-01-05",
                "entry": 100,
                "initial_stop": 95,
                "exit_price": 95,
                "quantity": 10,
                "realised_pnl": -50,
                "exit_reason": "STOP",
            }
        ],
    }
    data = pd.DataFrame(
        {
            "trade_date": ["2026-01-01", "2026-01-02", "2026-01-05"],
            "close": [100, 99, 95],
            "high": [102, 101, 96],
            "low": [99, 98, 94],
        }
    )
    result = audit_hull(state, {"TEST": data})
    assert result["rupee_metrics"]["net"] == -50
    assert result["r_metrics"]["net"] == -1
    assert result["same_close_entries"] == 1
    assert result["rupee_metrics"]["portfolio_max_drawdown"] == pytest.approx(50 / 300000 * 100)


def test_room_rechecked_after_gap_fill():
    d = replay_rows().iloc[:2].copy()
    d["enforce_room"] = True
    d["room_r"] = 1.5
    d.loc[1, ["open", "high", "low", "close"]] = [101, 103, 99, 102]
    result = simulate(d)
    assert not result["open"]
    assert not result["trades"]


def test_negative_monthly_return_does_not_block_progressive_recovery():
    d = features(prices())
    i = d.index[-1]
    d.loc[i, ["setup", "history_ok", "risk_ok", "volume_ok", "range_blocked", "deteriorating"]] = [
        "EARLY RECOVERY",
        True,
        True,
        True,
        False,
        False,
    ]
    d.loc[i, ["return22", "return44", "return66"]] = [-2, -4, -8]
    assert candidate_mask(d, "Momentum Ladder", "progressive").iloc[-1]
    assert not candidate_mask(d, "Momentum Ladder", "mature_control").iloc[-1]


def test_discontinuity_is_review_not_winning_trade():
    d = replay_rows()
    d.loc[2, ["open", "high", "low", "close"]] = [200, 210, 195, 205]
    result = simulate(d)
    assert not result["trades"]
    assert result["open"][0]["status"] == "REVIEW"
