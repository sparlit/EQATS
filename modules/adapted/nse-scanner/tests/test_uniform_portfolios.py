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


"""Economic invariants and execution scenarios, not implementation snapshots."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from portfolio_accounting import build_snapshot, render_messages
from portfolio_accounting.adapters import hull_snapshot, ladder_candidates, penny_candidates, v3_snapshot
from portfolio_accounting.ledger import LedgerConfig, advance


def holding(**overrides):
    return dict(
        trade_id="T",
        symbol="ABC",
        status="OPEN",
        entry=100,
        quantity=10,
        remaining_quantity=10,
        last_price=110,
        realised_pnl=0,
        fees=0,
        mark_date="2026-08-03",
        **overrides,
    )


def candidate(symbol="ABC", **overrides):
    c = {
        "symbol": symbol,
        "score": 80,
        "entry": 100,
        "entry_high": 103,
        "stop": 95,
        "target1": 110,
        "target2": 115,
        "max_stop_pct": 12,
    }
    c.update(overrides)
    return c


def bar(day, **overrides):
    b = {"date": day, "open": 100, "high": 105, "low": 99, "close": 103, "prev_close": 100, "entry_allowed": True}
    b.update(overrides)
    return {"ABC": b}


def test_partial_exit_cash_equity_and_pending_are_separate():
    p = holding()
    p.update(remaining_quantity=4, realised_pnl=120, fees=5)
    s = build_snapshot("V3", "2026-08-03", 10000, [p], [{"reserved_capital": 900}])
    assert s["invested_capital"] == 400
    assert s["available_cash"] == 9715  # 10000 - 1000 + (6*100 + 120) - 5
    assert s["market_value"] == 440
    assert s["equity"] == 10155
    assert s["total_pnl"] == 155
    assert s["reserved_capital"] == 900
    assert s["return_pct"] == pytest.approx(1.55)


def test_closed_trade_and_missing_mark_review_remain_accounted():
    closed = holding()
    closed.update(status="CLOSED", remaining_quantity=0, realised_pnl=-40)
    review = holding()
    review.update(trade_id="R", status="REVIEW", mark_date=None)
    s = build_snapshot("Hull", "2026-08-03", 10000, [closed, review])
    assert s["available_cash"] == 8960
    assert s["total_pnl"] == 60
    assert s["open_positions"] == 1
    assert len(s["warnings"]) == 2


@pytest.mark.parametrize(
    "change", [{"quantity": float("nan")}, {"remaining_quantity": 11}, {"fees": -1}, {"status": "PENDING"}]
)
def test_invalid_accounting_rejected(change):
    p = holding()
    p.update(change)
    with pytest.raises(ValueError):
        build_snapshot("V3", "2026-08-03", 10000, [p])


def test_native_adapters_preserve_economics_and_exclude_unfilled():
    raw = holding()
    raw.update(state="PARTIAL", remaining_quantity=4, realised_pnl=120, updated_date="2026-08-03")
    pending = {**raw, "trade_id": "P", "state": "READY"}
    s = v3_snapshot([raw, pending], "2026-08-03", 10000, {"T": "2026-08-01"})
    assert s["realised_pnl"] == 120
    assert s["unrealised_pnl"] == 40
    assert s["positions"][0]["entry_date"] == "2026-08-01"
    assert s["pending_setups"] == 1
    raw["state"] = "CORPORATE_ACTION_REVIEW"
    h = hull_snapshot({"last_run": "2026-08-03", "capital_base": 10000, "positions": [raw]})
    assert h["positions"][0]["remaining_quantity"] == 10
    assert h["positions"][0]["status"] == "REVIEW"


def test_signal_mapping_uses_only_actual_ready_and_shadow_levels():
    ready = {
        "symbol": "ABC",
        "state": "READY",
        "score": 80,
        "entry_low": 100,
        "entry_high": 102,
        "stop": 95,
        "target1": 110,
        "target2": 115,
    }
    assert len(penny_candidates({"candidates": [ready, {**ready, "state": "CONFIRMING"}]})) == 1
    report = {
        "multi_horizon_shadow": {
            "candidates": [
                {
                    "symbol": "ABC",
                    "primary_score": 80,
                    "trade_levels": {
                        "eligible_for_paper": True,
                        "entry_trigger": 100,
                        "stop": 95,
                        "target_1": 110,
                        "target_2": 115,
                    },
                }
            ]
        }
    }
    assert ladder_candidates(report)[0]["target2"] == 115
    with pytest.raises(ValueError):
        ladder_candidates({"shortlist": []})


def test_next_session_entry_rerun_restart_and_stop_gap(tmp_path):
    path = tmp_path / "p.sqlite"
    first = advance(path, "Penny", "2026-08-03", bar("2026-08-03"), [candidate()])
    assert first["open_positions"] == 0
    assert first["pending_setups"] == 1
    second = advance(path, "Penny", "2026-08-04", bar("2026-08-04"), [])
    assert second["open_positions"] == 1
    assert second == advance(path, "Penny", "2026-08-04", bar("2026-08-04"), [])
    closed = advance(path, "Penny", "2026-08-05", bar("2026-08-05", open=90, high=120, low=89, close=110), [])
    p = closed["positions"][0]
    assert p["exit_price"] == 90  # gap stop, not optimistic 95 or target 115
    assert p["realised_pnl"] == -10 * p["quantity"]
    assert closed["available_cash"] == closed["equity"]
    assert closed["reconciliation_residual"] == pytest.approx(0)


def test_same_bar_entry_stop_is_adverse_and_no_same_day_reentry(tmp_path):
    path = tmp_path / "p.sqlite"
    advance(path, "Penny", "2026-08-03", bar("2026-08-03"), [candidate()])
    s = advance(path, "Penny", "2026-08-04", bar("2026-08-04", low=94, high=120), [candidate()])
    assert s["closed_positions"] == 1
    assert s["pending_setups"] == 0
    assert s["positions"][0]["exit_price"] == 95


def test_locks_stale_prices_and_entry_restrictions(tmp_path):
    path = tmp_path / "p.sqlite"
    advance(path, "Penny", "2026-08-03", bar("2026-08-03"), [candidate()])
    s = advance(path, "Penny", "2026-08-04", bar("2026-08-04", entry_allowed=False), [])
    assert not s["positions"]
    s = advance(path, "Penny", "2026-08-05", bar("2026-08-05"), [])
    qty = s["positions"][0]["quantity"]
    s = advance(
        path, "Penny", "2026-08-06", bar("2026-08-06", open=90, high=90, low=90, close=90, exit_blocked=True), []
    )
    assert s["open_positions"] == 1
    assert s["unrealised_pnl"] == -10 * qty
    s = advance(path, "Penny", "2026-08-07", {}, [])
    assert s["positions"][0]["mark_date"] == "2026-08-06"
    assert s["warnings"]


def test_cash_risk_and_fee_limits(tmp_path):
    cfg = LedgerConfig(capital=1000, risk_fraction=0.5, max_position_fraction=1, max_total_risk_fraction=1, fee_bps=100)
    p = tmp_path / "p.sqlite"
    advance(p, "Penny", "2026-08-03", bar("2026-08-03"), [candidate()], config=cfg)
    s = advance(p, "Penny", "2026-08-04", bar("2026-08-04"), [], config=cfg)
    assert s["positions"][0]["quantity"] == 9
    assert s["available_cash"] == 91
    assert s["fees"] == 9
    assert s["equity"] == 1018


def test_ladder_target_one_does_not_invent_partial_exit_or_trail(tmp_path):
    p = tmp_path / "p.sqlite"
    advance(p, "Momentum Ladder", "2026-08-03", bar("2026-08-03"), [candidate()])
    advance(p, "Momentum Ladder", "2026-08-04", bar("2026-08-04"), [])
    s = advance(p, "Momentum Ladder", "2026-08-05", bar("2026-08-05", high=112), [])
    assert s["realised_pnl"] == 0
    assert s["positions"][0]["stop"] == 95
    assert s["positions"][0]["target1_hit"]


def test_transaction_rollback_changed_inputs_and_concurrent_retry(tmp_path):
    p = tmp_path / "p.sqlite"
    advance(p, "Penny", "2026-08-03", bar("2026-08-03"), [candidate()])
    with pytest.raises(ValueError):
        advance(p, "Penny", "2026-08-04", bar("2026-08-04"), [candidate("BAD", stop=120)])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: advance(p, "Penny", "2026-08-04", bar("2026-08-04"), []), range(2)))
    assert results[0] == results[1]
    assert results[0]["open_positions"] == 1
    with pytest.raises(ValueError, match="inputs changed"):
        advance(p, "Penny", "2026-08-04", bar("2026-08-04", close=104), [])
    with pytest.raises(ValueError, match="older"):
        advance(p, "Penny", "2026-08-01", {}, [])
    with sqlite3.connect(p) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2


def test_common_messages_paginate_and_escape():
    rows = []
    for i in range(30):
        p = holding()
        p.update(trade_id=str(i), symbol="A&B<1>")
        rows.append(p)
    s = build_snapshot("Hull", "2026-08-03", 100000, rows)
    pages = render_messages(s)
    assert len(pages) > 1
    assert all(len(p) <= 3400 for p in pages)
    assert "A&amp;B&lt;1&gt;" in "".join(pages)
    assert "Available cash" in pages[0]


def test_penny_and_ladder_portfolio_messages_offer_chart_and_dashboard_links():
    for scanner, selector in [("Penny", "penny"), ("Momentum Ladder", "ladder")]:
        snapshot = build_snapshot(scanner, "2026-09-23", 10000, [holding()])
        message = "\n".join(render_messages(snapshot))
        assert "Open ABC chart</a>" in message
        assert "symbol=NSE%3AABC" in message
        assert f"startapp={selector}" in message


def test_missing_session_rejected_and_native_cash_limit():
    from pine_hull.engine import PineConfig, _allocation

    rows = [
        {"state": "CLOSED", "realised_pnl": -10000},
        {"state": "CORPORATE_ACTION_REVIEW", "entry": 100, "quantity": 2900},
    ]
    assert _allocation(100, 95, rows, PineConfig(cash_accounting=True)) == 0


def test_missing_exchange_session_does_not_skip_stop(tmp_path):
    path = tmp_path / "p.sqlite"
    advance(path, "Penny", "2026-08-03", bar("2026-08-03"), [candidate()])
    with pytest.raises(ValueError, match="Missing market session"):
        advance(path, "Penny", "2026-08-05", bar("2026-08-05"), [], previous_session="2026-08-04")


def test_hull_opt_in_retry_does_not_manage_entry_bar_twice(tmp_path):
    from pine_hull.engine import PineConfig, run_daily
    from tests.test_pine_hull_engine import _database, _frame

    db, state = tmp_path / "m.db", tmp_path / "h.json"
    _database(db, _frame(end=200))
    first = run_daily(db, state_path=state, config=PineConfig(cash_accounting=True))
    before = state.read_bytes()
    second = run_daily(db, state_path=state, config=PineConfig(cash_accounting=True))
    assert first["created"]
    assert not second["created"]
    assert state.read_bytes() == before


def test_v3_opt_in_retry_does_not_resell_partial_quantity(tmp_path):
    from v2.daily_portfolio import process_portfolio_day
    from v2.lifecycle import new_position
    from v2.portfolio_store import PortfolioStore

    store = PortfolioStore(tmp_path / "v.db")
    store.initialize()
    p = new_position("ABC", "SWING_1_3M", "2026-08-03", 100, 95, 110, 120, 10)
    store.save_position(p, "WATCH")
    bars = {"ABC": {"open": 100, "low": 99, "high": 112, "close": 111}}
    first = process_portfolio_day(store, "2026-08-04", bars, skip_processed_session=True)
    before = store.all_positions()[0]
    second = process_portfolio_day(store, "2026-08-04", bars, skip_processed_session=True)
    assert first
    assert not second
    assert store.all_positions()[0] == before


def test_rollout_is_opt_in(monkeypatch):
    from portfolio_accounting.config import rollout_directory

    monkeypatch.delenv("UNIFORM_PAPER_PORTFOLIOS", raising=False)
    assert rollout_directory() is None
    monkeypatch.setenv("UNIFORM_PAPER_PORTFOLIOS", "true")
    assert rollout_directory() == "paper_portfolios"


def test_disposable_runner_without_master_matches_existing_gateway(tmp_path):
    from portfolio_accounting.service import market_bars
    from tests.test_pine_hull_engine import _database, _frame
    from v2.database import V2Database

    frame = _frame(end=200)
    db = tmp_path / "market.db"
    _database(db, frame)
    day = frame["trade_date"].iloc[-1].date().isoformat()
    bars = market_bars(V2Database(db), day)
    assert bars["PINE"]["entry_allowed"] is True
    assert bars["PINE"]["metadata_available"] is False
