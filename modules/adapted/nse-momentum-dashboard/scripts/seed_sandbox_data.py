from __future__ import annotations

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


"""Seeds cache/state_sandbox.db with realistic synthetic records (ledger,
tradebook, job runs, rebalance history, skipped symbols) using the app's
own state_db writer functions -- idempotent, only runs if the ledger is
still empty, so re-launching the sandbox doesn't duplicate data.
"""

import datetime as dt
import random

import state_db
from scripts import sandbox_mock_kite

import config


def seed_if_empty() -> None:
    if not state_db.get_cash_flows().empty:
        print("[sandbox] data already seeded, skipping")
        return
    print("[sandbox] seeding synthetic data...")

    universe = config.UNIVERSE or []
    if not universe:
        print("[sandbox] WARNING: config.UNIVERSE is empty, skipping seed")
        return
    rng = random.Random(7)
    held_symbols = rng.sample(universe, min(5, len(universe)))
    sandbox_mock_kite.seed_holdings(held_symbols)

    # --- Ledger: a handful of deposits/withdrawals over the last 2 months
    today = dt.date.today()
    ledger_entries = [
        (60, 500000.0, "Initial capital"),
        (45, 100000.0, "Second tranche"),
        (30, -20000.0, "Partial withdrawal"),
        (10, 50000.0, "Top-up"),
    ]
    for days_ago, amount, note in ledger_entries:
        state_db.record_cash_flow((today - dt.timedelta(days=days_ago)).isoformat(), amount, note)

    # --- Equity log: a rough rising-then-dipping curve for the Overview chart
    base = 630000.0
    for days_ago in range(60, -1, -3):
        today - dt.timedelta(days=days_ago)
        noise = rng.uniform(-0.015, 0.02)
        base *= 1 + noise
        state_db.log_equity_snapshot(round(base, 2), 600000.0 + (60 - days_ago) * 1500)

    # --- Skipped symbols
    skip_candidates = [s for s in universe if s not in held_symbols][:2]
    for sym in skip_candidates:
        state_db.add_skipped_symbol(sym, "sandbox test: illiquid / news risk")

    # --- Tradebook: a few closed trades (mixed win/loss) + open ones mirroring holdings
    closed_pool = [s for s in universe if s not in held_symbols][2:8]
    for i, sym in enumerate(closed_pool):
        entry_date = (today - dt.timedelta(days=90 - i * 7)).isoformat()
        entry_price = sandbox_mock_kite.fake_get_ltp([sym])[sym] * rng.uniform(0.8, 1.1)
        qty = rng.choice([5, 10, 15])
        stop = entry_price * 0.9
        state_db.record_trade_entry(
            sym,
            round(entry_price, 2),
            qty,
            round(stop, 2),
            snapshot={
                "score": round(rng.uniform(1.0, 3.5), 2),
                "rsi": round(rng.uniform(45, 78), 1),
                "pct_52w_high": round(rng.uniform(0.85, 1.0), 2),
                "vol_expansion": round(rng.uniform(1.0, 2.5), 2),
                "fundamental_score": round(rng.uniform(40, 95), 1),
                "entry_reason": f"Ranked #{i + 1} momentum candidate (sandbox seed)",
            },
            entry_date=entry_date,
        )
        exit_price = entry_price * rng.uniform(0.88, 1.25)
        reason = rng.choice(["stop_hit", "dropped out of top N rank", "closed below 200 EMA", "manual_square_off"])
        state_db.close_trade(sym, round(exit_price, 2), reason)

    for sym in held_symbols:
        h = sandbox_mock_kite._HOLDINGS_STATE[sym]
        pos_id = state_db.record_new_position(
            sym, h["average_price"], h["quantity"], round(h["average_price"] * 0.88, 2), None
        )
        state_db.record_trade_entry(
            sym,
            h["average_price"],
            h["quantity"],
            round(h["average_price"] * 0.88, 2),
            snapshot={
                "score": round(rng.uniform(1.0, 3.5), 2),
                "rsi": round(rng.uniform(45, 78), 1),
                "pct_52w_high": round(rng.uniform(0.85, 1.0), 2),
                "vol_expansion": round(rng.uniform(1.0, 2.5), 2),
                "fundamental_score": round(rng.uniform(40, 95), 1),
                "entry_reason": "Open sandbox holding",
            },
            position_id=pos_id,
        )

    # --- Job runs (Job Log page)
    for jt, trigger, status, mins_ago, summary, err in [
        ("rebalance_scan", "scheduled", "success", 60 * 20, "1 buys, 1 sells, 0 stop updates", None),
        ("gap_check", "scheduled", "success", 60 * 18, "no positions gapped below stop", None),
        ("screen_run", "scheduled", "success", 60 * 19, "208 candidates (67 passing all gates)", None),
        (
            "rebalance_scan",
            "manual",
            "failed",
            60 * 40,
            None,
            (
                "requests.exceptions.ConnectionError: ('Connection aborted.', "
                "ConnectionResetError(104, 'Connection reset by peer'))\n"
                "(sandbox synthetic failure for testing)"
            ),
        ),
        ("fundamentals_refresh", "scheduled", "success", 60 * 24 * 2, "208/210 scored", None),
    ]:
        run_id = state_db.start_job_run(jt, trigger)
        conn = state_db.get_conn()
        started = (dt.datetime.now() - dt.timedelta(minutes=mins_ago)).isoformat()
        finished = (dt.datetime.now() - dt.timedelta(minutes=mins_ago - 1)).isoformat()
        conn.execute(
            "UPDATE job_runs SET started_at = ?, finished_at = ?, duration_sec = ?, "
            "status = ?, summary = ?, error_message = ? WHERE id = ?",
            (started, finished, 60.0, status, summary, err, run_id),
        )
        conn.commit()
        conn.close()

    print(
        f"[sandbox] seeded: {len(ledger_entries)} ledger entries, "
        f"{len(held_symbols)} open positions, {len(closed_pool)} closed trades, "
        f"{len(skip_candidates)} skipped symbols, 5 job runs"
    )
