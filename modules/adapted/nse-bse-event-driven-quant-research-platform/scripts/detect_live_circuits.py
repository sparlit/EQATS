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


"""Detect TODAY's circuit hits using Upstox snapshot limits + live prices.

Compares current market prices against the previous snapshot's circuit limits
to identify stocks that hit upper/lower circuits today. Generates signals
and paper trades for circuit_breakout hypothesis.

Usage:
    python scripts/detect_live_circuits.py
    python scripts/detect_live_circuits.py --dry-run
"""


import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config.connections import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def get_yesterday_limits(engine) -> dict[str, dict]:
    """Get the most recent Upstox snapshot circuit limits (reference for today's detection)."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sa.text("""
            SELECT symbol, prev_close, upper_circuit, lower_circuit, filter_pct
            FROM stock_circuit_limits
            WHERE source = 'upstox_snapshot'
            AND trade_date = (SELECT MAX(trade_date) FROM stock_circuit_limits WHERE source = 'upstox_snapshot')
            AND upper_circuit > 0
        """)
            )
            .mappings()
            .fetchall()
        )
    return {r["symbol"]: dict(r) for r in rows}


def get_live_prices_from_upstox(engine) -> dict[str, float]:
    """Get live LTP from Upstox for stocks with circuit limits."""
    import httpx
    from indian_quant.config.settings import UpstoxConfig

    uc = UpstoxConfig()
    token = uc.resolve_token()
    if not token:
        log.warning("No Upstox token, falling back to cached_signals")
        return get_live_prices_fallback(engine)

    # Get instrument keys for stocks with circuit limits
    import pandas as pd

    master_path = Path("data/upstox_master.csv.gz")
    if not master_path.exists():
        return get_live_prices_fallback(engine)

    master = pd.read_csv(master_path, compression="gzip", dtype=str)
    nse = master[master["exchange"] == "NSE_EQ"]
    sym_to_key = dict(zip(nse["tradingsymbol"], nse["instrument_key"], strict=False))

    with engine.connect() as conn:
        syms = [
            r[0]
            for r in conn.execute(
                sa.text("SELECT DISTINCT symbol FROM stock_circuit_limits WHERE source='upstox_snapshot'")
            ).fetchall()
        ]

    keys = [sym_to_key[s] for s in syms if s in sym_to_key]
    if not keys:
        return get_live_prices_fallback(engine)

    # Fetch LTP in batches
    prices = {}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    for i in range(0, len(keys), 200):
        batch = keys[i : i + 200]
        keys_csv = ",".join(batch)
        try:
            resp = httpx.get(
                "https://api.upstox.com/v2/market-quote/quotes",
                params={"instrument_key": keys_csv},
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                for key, val in data.items():
                    if isinstance(val, dict) and val.get("last_price"):
                        # Extract symbol from response key
                        parts = key.split(":")
                        sym = parts[-1] if len(parts) > 1 else key
                        prices[sym] = float(val["last_price"])
        except Exception as e:
            log.warning(f"Upstox batch failed: {e}")

    log.info(f"  Fetched live LTP for {len(prices)} stocks from Upstox")
    return prices


def get_live_prices_fallback(engine) -> dict[str, float]:
    """Fallback: use cached_signals latest close."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sa.text("""
            SELECT DISTINCT ON (symbol) symbol, close
            FROM cached_signals
            WHERE signal_date = (SELECT MAX(signal_date) FROM cached_signals)
        """)
            )
            .mappings()
            .fetchall()
        )
    return {r["symbol"]: float(r["close"]) for r in rows}


def detect_circuit_hits(
    limits: dict[str, dict],
    prices: dict[str, float],
) -> list[dict]:
    """Detect stocks that hit their circuit limits today."""
    hits = []
    for sym, lim in limits.items():
        if sym not in prices:
            continue
        close = prices[sym]
        upper = lim["upper_circuit"]
        lower = lim["lower_circuit"]
        prev = lim["prev_close"]
        filt = lim["filter_pct"]

        upper_hit = close >= upper * 0.998
        lower_hit = close <= lower * 1.002

        if upper_hit or lower_hit:
            hits.append(
                {
                    "symbol": sym,
                    "close": close,
                    "prev_close": prev,
                    "upper_circuit": upper,
                    "lower_circuit": lower,
                    "filter_pct": filt,
                    "upper_hit": upper_hit,
                    "lower_hit": lower_hit,
                    "pct_from_prev": round((close / prev - 1) * 100, 2) if prev > 0 else 0,
                }
            )

    return sorted(hits, key=lambda x: abs(x["pct_from_prev"]), reverse=True)


def record_signals(engine, hits: list[dict], dry_run: bool = False, top_n: int = 7) -> int:
    """Record circuit hit signals and paper trades.

    Only the top_n strongest hits (by abs % move) become paper trades.
    All hits still get recorded as hypothesis_signals for analysis.
    """
    today = date.today().isoformat()
    recorded = 0

    for i, hit in enumerate(hits):
        sym = hit["symbol"]
        signal_type = "circuit_upper_breakout" if hit["upper_hit"] else "circuit_lower_reversal"
        strength = 80.0 if hit["filter_pct"] >= 10 else 60.0
        entry = hit["close"]
        stop = round(entry * 0.95, 2) if hit["upper_hit"] else round(entry * 1.05, 2)
        target = round(entry * 1.10, 2) if hit["upper_hit"] else round(entry * 0.92, 2)

        if dry_run:
            log.info(
                f"  DRY RUN: {sym} {signal_type} entry=₹{entry} stop=₹{stop} target=₹{target} filt={hit['filter_pct']}%"
            )
            recorded += 1
            continue

        # Check if already has open trade for this symbol
        with engine.connect() as conn:
            existing = conn.execute(
                sa.text("""
                SELECT COUNT(*) FROM hypothesis_trades
                WHERE hypothesis_id = 2 AND symbol = :sym AND status = 'OPEN'
            """),
                {"sym": sym},
            ).scalar()
            if existing > 0:
                log.info(f"  SKIP {sym}: already has open trade")
                continue

        # Always record the signal for analysis (skip if already recorded today)
        with engine.connect() as conn:
            dup_sig = conn.execute(
                sa.text("""
                SELECT COUNT(*) FROM hypothesis_signals
                WHERE hypothesis_id = 2 AND symbol = :sym
                  AND signal_date = :date AND signal_type = :stype
            """),
                {"sym": sym, "date": today, "stype": signal_type},
            ).scalar()
            if dup_sig > 0:
                log.info(f"  SKIP {sym}: signal already exists for today")
                continue

        with engine.begin() as conn:
            sig_id = conn.execute(
                sa.text("""
                INSERT INTO hypothesis_signals
                    (hypothesis_id, symbol, signal_date, signal_type, strength,
                     entry_price, stop_loss, target_price, close, vol_z, notes)
                VALUES (2, :sym, :date, :stype, :str,
                        :entry, :stop, :target, :close, 0.0, :notes)
                RETURNING id
            """),
                {
                    "sym": sym,
                    "date": today,
                    "stype": signal_type,
                    "str": strength,
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "close": entry,
                    "notes": (
                        f"live_detect filter={hit['filter_pct']}% "
                        f"prev=₹{hit['prev_close']} "
                        f"upper=₹{hit['upper_circuit']} "
                        f"pct_from_prev={hit['pct_from_prev']}%"
                    ),
                },
            ).scalar()

        # Only top_n signals become paper trades
        if i >= top_n:
            log.info(f"  SKIP {sym}: outside top {top_n} (rank {i + 1})")
            continue

        # Record hypothesis trade + paper signal
        with engine.begin() as conn:
            # Record hypothesis trade
            capital_per_pos = 100_000
            qty = max(1, int(capital_per_pos / entry))
            entry_value = round(qty * entry, 2)
            conn.execute(
                sa.text("""
                INSERT INTO hypothesis_trades
                    (hypothesis_id, symbol, entry_date, entry_price, qty,
                     entry_value, signal_id, stop_pct, horizon_days, status)
                VALUES (2, :sym, :date, :entry, :qty,
                        :entry_value, :sig_id, 0.05, 5, 'OPEN')
            """),
                {"sym": sym, "date": today, "entry": entry, "qty": qty, "entry_value": entry_value, "sig_id": sig_id},
            )

            # Record paper signal
            pos_val = qty * entry
            risk = qty * entry * 0.05
            paper_id = conn.execute(
                sa.text("""
                INSERT INTO paper_signals
                    (created_at, symbol, segment, side, close_at_signal, qty,
                     horizon_days, stop_pct, status, note,
                     entry_date, position_value, risk_amount, horizon_label,
                     capital_allocated, conviction_score, kelly_fraction, hypothesis_id)
                VALUES (:created_at, :sym, 'NSE_EQ', 'BUY', :close, :qty,
                        5, 0.05, 'OPEN', :note,
                        :date, :pos_val, :risk, '5d',
                        :cap, :conviction, 0.0, 2)
                RETURNING id
            """),
                {
                    "created_at": datetime.now().isoformat()[:19],
                    "sym": sym,
                    "close": entry,
                    "qty": qty,
                    "note": (
                        f"live_circuit {signal_type} filter={hit['filter_pct']}% pct_from_prev={hit['pct_from_prev']}%"
                    ),
                    "date": today,
                    "pos_val": round(pos_val, 2),
                    "risk": round(risk, 2),
                    "cap": capital_per_pos,
                    "conviction": round(strength / 100, 4),
                },
            ).scalar()

        # Auto-journal: sync journal with live trade
        from indian_quant.storage.pg_metadata import PgMetadataStore

        PgMetadataStore(engine).journal_record_on_entry(
            paper_trade_id=paper_id,
            symbol=sym,
            entry_date=str(today),
            entry_price=float(entry),
            entry_signal=f"circuit_breakout {signal_type}",
            setup_type="circuit_breakout",
            stop_loss=round(float(stop), 2),
            target_price=round(float(target), 2),
            position_size=qty,
            risk_amount=round(risk, 2),
            conviction=round(strength / 100, 4),
        )

        recorded += 1
        log.info(f"  RECORDED: {sym} {signal_type} entry=₹{entry} stop=₹{stop} target=₹{target}")

    return recorded


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect live circuit hits")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top", type=int, default=7, help="Top N hits to paper trade (default: 7)")
    args = parser.parse_args()

    engine = get_engine()

    log.info("Loading yesterday's circuit limits...")
    limits = get_yesterday_limits(engine)
    log.info(f"  {len(limits)} stocks with circuit limits")

    if not limits:
        log.warning("No yesterday snapshot found. Run snapshot_circuit_limits.py first.")
        return 1

    log.info("Loading live prices from Upstox...")
    prices = get_live_prices_from_upstox(engine)
    log.info(f"  {len(prices)} stocks with live prices")

    log.info("Detecting circuit hits...")
    hits = detect_circuit_hits(limits, prices)
    log.info(f"  {len(hits)} circuit hits detected")

    for h in hits[:10]:
        direction = "UPPER" if h["upper_hit"] else "LOWER"
        log.info(
            f"  {h['symbol']}: {direction} hit ₹{h['close']} "
            f"(prev=₹{h['prev_close']} upper=₹{h['upper_circuit']} "
            f"pct={h['pct_from_prev']}%)"
        )

    if hits:
        recorded = record_signals(engine, hits, dry_run=args.dry_run, top_n=args.top)
        log.info(f"Recorded: {recorded} signals + paper trades (top {args.top})")
    else:
        log.info("No circuit hits today")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
