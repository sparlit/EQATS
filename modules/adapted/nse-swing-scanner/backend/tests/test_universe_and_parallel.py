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


"""Tests for the new top-N universe + parallel run_scan."""
import time
from unittest.mock import patch

import pandas as pd
import pytest
import scanner
from universe import NIFTY_INDEX_URLS, fetch_universe


def _fake_universe(n: int) -> pd.DataFrame:
    """Build a synthetic NSE-shaped universe DataFrame."""
    return pd.DataFrame(
        {
            "company_name": [f"Company {i}" for i in range(n)],
            "industry": ["Financial Services"] * n,
            "symbol": [f"SYM{i:03d}" for i in range(n)],
            "series": ["EQ"] * n,
            "isin": ["INE000000000"] * n,
            "yf_ticker": [f"SYM{i:03d}.NS" for i in range(n)],
        }
    )


def test_universe_top_n_validates_input():
    """top_n outside {100, 200, 500} should fall back to 500."""
    with patch("universe._fetch_csv", return_value=_fake_universe(500)) as mocked:
        df = fetch_universe(top_n=300)
    assert len(df) == 500
    # Falls back to the 500 URL set
    args, _ = mocked.call_args
    assert args[0] == NIFTY_INDEX_URLS[500]


def test_universe_top_n_selects_correct_endpoint():
    with patch("universe._fetch_csv", return_value=_fake_universe(100)) as mocked:
        df = fetch_universe(top_n=100)
    assert len(df) == 100
    args, _ = mocked.call_args
    assert args[0] == NIFTY_INDEX_URLS[100]


def test_universe_preserves_csv_order():
    """Top-N universes must remain ranked by market cap (which is the CSV order)."""
    fake = _fake_universe(100)
    with patch("universe._fetch_csv", return_value=fake):
        df = fetch_universe(top_n=100)
    # Order should be preserved exactly (no sorting)
    assert list(df["symbol"]) == [f"SYM{i:03d}" for i in range(100)]


# --- run_scan with workers ------------------------------------------------


def _patched_shared_fetches():
    """Return minimal valid shared-fetch stubs."""
    return {
        "fetch_surveillance_list": {"status": "flag_only", "data": {}, "source": "none"},
        "fetch_bhavcopy": {"status": "source_failed", "data": {}, "source": "nse:bhavcopy"},
        "compute_nifty50_context": {"index_pct_from_ema200": -2.0, "error": None},
        "evaluate_stock": lambda rdict, **kwargs: {
            **rdict,
            "tech_current_price": 100.0,
            "tech_rsi14": 30.0,
            "tech_pct_off_52wk_high": -20.0,
            "tech_atr14": 5.0,
            "tech_target_1": 105.0,
            "tech_stop_loss": 95.0,
            "tech_adv_value_inr": 20_00_00_000,
            "tech_adv_sessions": 20,
            "delivery_value_inr": 1_000_000_000,
            "delivery_kind": "actual",
            "delivery_source_status": "ok",
            "surveillance_is_restricted": False,
            "surveillance_source_status": "flag_only",
            "fscore_f_score": 7,
            "fscore_f_score_components_available": 9,
            "pe5y_avg_pe_5y": 25.0,
            "pe5y_trailing_pe_check": 22.0,
            "holdings_data": {"promoter_pct": 50.0, "fii_pct": 20.0, "dii_pct": 20.0, "conviction_pct": 90.0},
            "holdings_status": "ok",
            "corporate_actions_data": {"has_excluded_action": False, "actions": []},
            "corporate_actions_status": "ok",
            "market_index_pct_from_ema200": -2.0,
            "market_correction_factor": 1.0,
            "gate_pass": True,
            "gate_fail_reason": None,
            "swing_score": 80.0,
            "sub_scores": {"valuation_compression": 0.5},
        },
        "fetch_holdings": {
            "status": "ok",
            "source": "screener.in",
            "data": {"promoter_pct": 50.0, "fii_pct": 20.0, "dii_pct": 20.0, "conviction_pct": 90.0},
        },
        "fetch_corporate_actions": {
            "status": "ok",
            "data": {"has_excluded_action": False, "actions": []},
        },
    }


def test_run_scan_uses_thread_pool(monkeypatch):
    """run_scan should call per-stock work via a thread pool, not sequentially."""
    fake_universe = _fake_universe(20)
    stubs = _patched_shared_fetches()

    call_log = []

    def fake_fetch_universe(*args, **kwargs):
        call_log.append("fetch_universe")
        return fake_universe

    def fake_fetch_surveillance_list():
        call_log.append("fetch_surveillance_list")
        return stubs["fetch_surveillance_list"]

    def fake_fetch_bhavcopy(*, universe_symbols=None, universe_yf_tickers=None):
        call_log.append("fetch_bhavcopy")
        return stubs["fetch_bhavcopy"]

    def fake_compute_nifty50_context():
        call_log.append("compute_nifty50_context")
        return stubs["compute_nifty50_context"]

    def fake_fetch_holdings(symbol):
        call_log.append(("fetch_holdings", symbol))
        return stubs["fetch_holdings"]

    def fake_fetch_corporate_actions(symbol):
        call_log.append(("fetch_corporate_actions", symbol))
        return stubs["fetch_corporate_actions"]

    def fake_evaluate_stock(rdict, **kwargs):
        call_log.append(("evaluate_stock", rdict["symbol"]))
        return stubs["evaluate_stock"](rdict, **kwargs)

    monkeypatch.setattr(scanner, "fetch_universe", fake_fetch_universe)
    monkeypatch.setattr(scanner, "fetch_surveillance_list", fake_fetch_surveillance_list)
    monkeypatch.setattr(scanner, "fetch_bhavcopy", fake_fetch_bhavcopy)
    monkeypatch.setattr(scanner, "compute_nifty50_context", fake_compute_nifty50_context)
    monkeypatch.setattr(scanner, "fetch_holdings", fake_fetch_holdings)
    monkeypatch.setattr(scanner, "fetch_corporate_actions", fake_fetch_corporate_actions)
    monkeypatch.setattr(scanner, "evaluate_stock", fake_evaluate_stock)

    df = scanner.run_scan(top_n=100, sample_size=20, workers=4, sleep_between_calls=0)

    # Shared fetches called exactly once each
    assert call_log.count("fetch_surveillance_list") == 1
    assert call_log.count("fetch_bhavcopy") == 1
    assert call_log.count("compute_nifty50_context") == 1
    # Per-stock fetches called once per stock (not per worker)
    holdings_calls = [c for c in call_log if isinstance(c, tuple) and c[0] == "fetch_holdings"]
    assert len(holdings_calls) == 20
    corp_calls = [c for c in call_log if isinstance(c, tuple) and c[0] == "fetch_corporate_actions"]
    assert len(corp_calls) == 20
    eval_calls = [c for c in call_log if isinstance(c, tuple) and c[0] == "evaluate_stock"]
    assert len(eval_calls) == 20
    assert len(df) == 20


def test_run_scan_workers_capped_to_universe_size(monkeypatch):
    """workers should never exceed the universe size."""
    fake_universe = _fake_universe(3)
    stubs = _patched_shared_fetches()

    monkeypatch.setattr(scanner, "fetch_universe", lambda *a, **k: fake_universe)
    monkeypatch.setattr(scanner, "fetch_surveillance_list", lambda: stubs["fetch_surveillance_list"])
    monkeypatch.setattr(
        scanner, "fetch_bhavcopy", lambda *, universe_symbols=None, universe_yf_tickers=None: stubs["fetch_bhavcopy"]
    )
    monkeypatch.setattr(scanner, "compute_nifty50_context", lambda: stubs["compute_nifty50_context"])
    monkeypatch.setattr(scanner, "fetch_holdings", lambda s: stubs["fetch_holdings"])
    monkeypatch.setattr(scanner, "fetch_corporate_actions", lambda s: stubs["fetch_corporate_actions"])
    monkeypatch.setattr(scanner, "evaluate_stock", stubs["evaluate_stock"])

    # workers=20 should be silently capped to 3
    df = scanner.run_scan(top_n=100, workers=20, sleep_between_calls=0)
    assert len(df) == 3


def test_run_scan_worker_exception_does_not_kill_scan(monkeypatch):
    """A bad worker must produce a row with gate_pass=False, not crash the scan."""
    fake_universe = _fake_universe(3)
    stubs = _patched_shared_fetches()

    monkeypatch.setattr(scanner, "fetch_universe", lambda *a, **k: fake_universe)
    monkeypatch.setattr(scanner, "fetch_surveillance_list", lambda: stubs["fetch_surveillance_list"])
    monkeypatch.setattr(
        scanner, "fetch_bhavcopy", lambda *, universe_symbols=None, universe_yf_tickers=None: stubs["fetch_bhavcopy"]
    )
    monkeypatch.setattr(scanner, "compute_nifty50_context", lambda: stubs["compute_nifty50_context"])
    monkeypatch.setattr(scanner, "fetch_holdings", lambda s: stubs["fetch_holdings"])
    monkeypatch.setattr(scanner, "fetch_corporate_actions", lambda s: stubs["fetch_corporate_actions"])

    def flaky_evaluate(rdict, **kwargs):
        if rdict["symbol"] == "SYM001":
            msg = "simulated worker crash"
            raise RuntimeError(msg)
        return stubs["evaluate_stock"](rdict, **kwargs)

    monkeypatch.setattr(scanner, "evaluate_stock", flaky_evaluate)

    df = scanner.run_scan(top_n=100, workers=2, sleep_between_calls=0)
    assert len(df) == 3
    crashed = df[df["symbol"] == "SYM001"]
    assert crashed.iloc[0]["gate_pass"] is False or not crashed.iloc[0]["gate_pass"]
    assert "exception" in str(crashed.iloc[0]["gate_fail_reason"])
