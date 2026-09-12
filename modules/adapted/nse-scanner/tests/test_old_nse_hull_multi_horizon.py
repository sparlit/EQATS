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


import json
import sqlite3

import pandas as pd
from old_nse_hull.engine import _tradeable_prices, render_period_report
from old_nse_hull.multi_horizon.comparison import summarize
from old_nse_hull.multi_horizon.data_health import evaluate as evaluate_data_health
from old_nse_hull.multi_horizon.engine import run_shadow
from old_nse_hull.multi_horizon.features import latest_features
from old_nse_hull.multi_horizon.historical_replay import run as run_historical_replay
from old_nse_hull.multi_horizon.market_context import load_context
from old_nse_hull.multi_horizon.paper_lifecycle import update as update_paper_lifecycle
from old_nse_hull.multi_horizon.readiness import assess
from old_nse_hull.multi_horizon.telegram import MAX_MESSAGE_CHARS, render_messages
from old_nse_hull.multi_horizon.trade_levels import build_levels
from old_nse_hull.multi_horizon.walkforward import run as run_walkforward


def _prices(days: int = 330) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=days)
    rows = []
    for symbol, start, step in (("LEADER", 100.0, 0.8), ("LAGGARD", 250.0, 0.1)):
        for index, date in enumerate(dates):
            close = start + step * index
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "open": close - 1,
                    "high": close + 0.25,
                    "low": close - 2,
                    "close": close,
                    "volume": 200_000 if symbol == "LEADER" else 80_000,
                    "delivery_pct": 60.0,
                    "turnover_lacs": 400.0,
                }
            )
    return pd.DataFrame(rows)


def test_previous_breakout_high_excludes_the_current_candle():
    features = latest_features(_prices())
    leader = features.set_index("symbol").loc["LEADER"]
    assert leader["previous_20d_high"] < leader["close"] + 0.25
    assert leader["close"] > leader["previous_20d_high"]


def test_shadow_records_lifecycle_without_touching_baseline_tables(tmp_path):
    db_path = tmp_path / "scanner.db"
    result = run_shadow(_prices(), db_path)
    assert result["mode"] == "SHADOW"
    assert result["eligible"] == 2
    assert result["qualified"] >= 1
    json.dumps(result, default=str)
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"old_nse_hull_multi_horizon_daily"}
        assert conn.execute("SELECT COUNT(*) FROM old_nse_hull_multi_horizon_daily").fetchone()[0] == 2


def test_old_hull_tradeability_gate_excludes_etf_and_terminal_merger(tmp_path, monkeypatch):
    lifecycle = tmp_path / "corporate_data" / "normalized"
    lifecycle.mkdir(parents=True)
    (lifecycle / "security_lifecycle_events.csv").write_text(
        "symbol,terminal,last_trading_date,event_type,successor_symbol,notes\n"
        "JBCHEPHARM,1,2025-07-01,AMALGAMATION,TORNTPHARM,merged\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with sqlite3.connect(tmp_path / "scanner.db"):
        pass
    prices = _prices().assign(
        symbol=lambda frame: frame["symbol"].replace({"LEADER": "NEXT50IETF", "LAGGARD": "JBCHEPHARM"})
    )
    filtered, summary = _tradeable_prices(prices, tmp_path / "scanner.db")
    assert filtered.empty
    assert summary["rejection_counts"] == {"ETF_SECURITY": 1, "TERMINAL_MERGER": 1}


def test_shadow_rerun_is_idempotent_for_same_session(tmp_path):
    db_path = tmp_path / "scanner.db"
    prices = _prices()
    run_shadow(prices, db_path)
    second = run_shadow(prices, db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM old_nse_hull_multi_horizon_daily").fetchone()[0] == 2
    assert {row["lifecycle_status"] for row in second["candidates"]} <= {"CARRY_FORWARD", "FIRST_QUALIFIED"}


def test_shadow_derives_a_transition_from_shared_prior_price_session(tmp_path):
    result = run_shadow(_prices(), tmp_path / "scanner.db")
    assert {row["lifecycle_status"] for row in result["candidates"]} <= {
        "NEWLY_QUALIFIED",
        "CARRY_FORWARD",
        "UPGRADED",
        "DOWNGRADED",
        "FIRST_QUALIFIED",
    }


def test_shadow_comparison_ledger_is_idempotent_and_tracks_validation(tmp_path):
    db_path = tmp_path / "scanner.db"
    state_path = tmp_path / "shadow.json"
    first = run_shadow(_prices(), db_path, ["LEADER", "BASELINE"], state_path)
    second = run_shadow(_prices(), db_path, ["LEADER", "BASELINE"], state_path)
    assert first["comparison_summary"]["sessions_observed"] == 1
    assert second["comparison_summary"]["sessions_observed"] == 1
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(persisted["sessions"]) == 1
    assert persisted["sessions"].values().__iter__().__next__()["overlap_symbols"] == ["LEADER"]


def test_shadow_validation_is_a_single_non_watchlist_message():
    candidates = [
        {
            "symbol": f"S{index}",
            "lifecycle_status": "NEWLY_QUALIFIED",
            "primary_horizon": "1M",
            "primary_score": 80,
            "confluence_score": 75,
            "confirming_horizons": ["3M"],
            "close": 123.45,
            "atr_pct": 3.2,
            "score_1m": 80,
            "score_3m": 75,
            "score_6m": 60,
            "score_12m": 55,
        }
        for index in range(40)
    ]
    messages = render_messages(
        {
            "multi_horizon_shadow": {
                "as_of_date": "2026-08-20",
                "candidates": candidates,
                "comparison_summary": {
                    "sessions_observed": 1,
                    "target_sessions": 20,
                    "average_baseline_candidates": 25,
                    "average_shadow_candidates": 40,
                    "average_overlap": 8,
                },
            }
        }
    )
    assert len(messages) == 1
    assert "SYSTEM VALIDATION" in messages[0]
    assert "NOT A WATCHLIST" in messages[0]
    assert "S0" not in messages[0]


def test_period_report_keeps_shadow_promotion_blocked_before_20_sessions(tmp_path):
    summary = summarize(tmp_path / "missing.json")
    report = {"as_of_date": "2026-08-20", "discovery_qualified": 4, "ready": 1, "watch": 3}
    text = render_period_report(report, "weekly", summary)
    assert "WEEKLY SUMMARY" in text
    assert "Technical model comparison is reported separately" in text


def test_trade_levels_reject_a_wide_structural_stop_without_clamping():
    levels = build_levels(
        {"primary_horizon": "1M", "close": 100, "atr": 2, "previous_20d_high": 100, "previous_10d_low": 80}
    )
    assert not levels["eligible_for_paper"]
    assert levels["rejection_code"] == "risk_exceeds_maximum"


def test_paper_lifecycle_waits_until_a_later_session_to_enter(tmp_path):
    path = tmp_path / "paper.json"
    candidate = {
        "symbol": "AAA",
        "high": 101,
        "low": 99,
        "trade_levels": {
            "eligible_for_paper": True,
            "entry_trigger": 102,
            "stop": 98,
            "target_1": 108,
            "target_2": 112,
        },
    }
    first = update_paper_lifecycle(path, "2026-08-20", [candidate])
    assert first["watching"] == 1
    assert first["open"] == 0
    next_day = {"symbol": "AAA", "high": 103, "low": 100}
    second = update_paper_lifecycle(path, "2026-08-21", [], [next_day])
    assert second["watching"] == 0
    assert second["open"] == 1
    assert any(event["event"] == "PAPER_ENTERED" for event in second["events_today"])


def test_paper_lifecycle_records_stop_after_entry(tmp_path):
    path = tmp_path / "paper.json"
    candidate = {
        "symbol": "AAA",
        "high": 101,
        "low": 99,
        "trade_levels": {
            "eligible_for_paper": True,
            "entry_trigger": 102,
            "stop": 98,
            "target_1": 108,
            "target_2": 112,
        },
    }
    update_paper_lifecycle(path, "2026-08-20", [candidate])
    update_paper_lifecycle(path, "2026-08-21", [], [{"symbol": "AAA", "high": 103, "low": 100}])
    stopped = update_paper_lifecycle(path, "2026-08-22", [], [{"symbol": "AAA", "high": 100, "low": 97}])
    assert stopped["closed"] == 1
    assert any(event["event"] == "PAPER_STOPPED" for event in stopped["events_today"])


def test_market_context_uses_current_nifty_500_and_breadth(tmp_path):
    db_path = tmp_path / "context.db"
    dates = pd.bdate_range("2025-01-01", periods=330)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE index_perf (index_name TEXT, date TEXT, close REAL)")
        conn.executemany(
            "INSERT INTO index_perf VALUES (?, ?, ?)",
            [("Nifty 500", date.date().isoformat(), 100 + index) for index, date in enumerate(dates)],
        )
    context = load_context(db_path, latest_features(_prices()))
    assert context["status"] == "CURRENT"
    assert context["benchmark"] == "Nifty 500"
    assert set(context["benchmark_returns"]) == {"1M", "3M", "6M", "12M"}


def test_data_health_excludes_blacklisted_symbols(tmp_path):
    db_path = tmp_path / "health.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE blacklist (symbol TEXT, date TEXT)")
        conn.execute("INSERT INTO blacklist VALUES ('LEADER', '2025-12-31')")
    health = evaluate_data_health(db_path, latest_features(_prices()))
    assert health["status"] == "CURRENT"
    assert health["blocked_symbols"] == ["LEADER"]


def test_walkforward_uses_existing_prices_only():
    result = run_walkforward(_prices(), holding_sessions=5, sample_step=5, top_n=2)
    assert result["status"] == "COMPLETE"
    assert result["method"] == "screen_return_proxy_not_execution_backtest"
    assert result["observations"] > 0


def test_readiness_blocks_without_real_shadow_window(tmp_path):
    walkforward = tmp_path / "walkforward.json"
    walkforward.write_text(json.dumps({"status": "COMPLETE", "observations": 10}), encoding="utf-8")
    result = assess(tmp_path / "missing.json", walkforward, tmp_path / "missing-history.json")
    assert result["status"] == "BLOCKED"
    assert "historical_replay_0_of_20" in result["blockers"]
    assert "live_operational_sessions_0_of_5" in result["blockers"]


def test_historical_replay_uses_as_of_history_without_downloads(tmp_path):
    result = run_historical_replay(_prices(), tmp_path / "replay.db", tmp_path / "replay.json", sessions=2)
    assert result["mode"] == "HISTORICAL_REPLAY"
    assert result["sessions_completed"] == 2
    assert result["comparison_summary"]["sessions_observed"] == 2
