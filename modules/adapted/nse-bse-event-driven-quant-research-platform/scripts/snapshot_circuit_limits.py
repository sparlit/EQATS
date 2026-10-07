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


"""Snapshot circuit limits from Upstox V2 Market Quotes API.

Fetches live upper/lower circuit limits for all universe stocks and stores
them in stock_circuit_limits with source='upstox_snapshot'.

Usage:
    python scripts/snapshot_circuit_limits.py
    python scripts/snapshot_circuit_limits.py --universe circuit_breakout
"""


import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.adapters.upstox.rest import UpstoxRestClient
from indian_quant.config.connections import get_engine
from indian_quant.config.settings import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BATCH_SIZE = 100  # Upstox supports up to 500, use 100 for safety


def get_universe_symbols(engine, hypothesis_name: str | None = None) -> list[str]:
    """Get universe symbols from hypothesis_stocks or all cached_signals symbols."""
    with engine.connect() as conn:
        if hypothesis_name:
            rows = conn.execute(
                sa.text("""
                SELECT hs.symbol FROM hypothesis_stocks hs
                JOIN hypotheses h ON h.id = hs.hypothesis_id
                WHERE h.name = :name AND hs.removed_at IS NULL
            """),
                {"name": hypothesis_name},
            ).fetchall()
        else:
            rows = conn.execute(sa.text("SELECT DISTINCT symbol FROM cached_signals")).fetchall()
    return [r[0] for r in rows]


def resolve_instrument_keys(symbols: list[str]) -> list[str]:
    """Resolve NSE symbols to Upstox instrument keys using master CSV."""
    master_path = Path("data/upstox_master.csv.gz")
    if not master_path.exists():
        log.error("upstox_master.csv.gz not found")
        return []

    import pandas as pd

    master = pd.read_csv(master_path, compression="gzip", dtype=str)
    # Filter NSE_EQ instruments (column is 'tradingsymbol' not 'trading_symbol')
    nse = master[master["exchange"] == "NSE_EQ"]
    # Build symbol -> instrument_key mapping
    sym_to_key = {}
    for _, row in nse.iterrows():
        trading_symbol = row.get("tradingsymbol", "")
        instrument_key = row.get("instrument_key", "")
        if trading_symbol and instrument_key:
            sym_to_key[trading_symbol] = instrument_key

    keys = []
    missing = []
    for sym in symbols:
        key = sym_to_key.get(sym)
        if key:
            keys.append(key)
        else:
            missing.append(sym)

    if missing:
        log.warning(f"Could not resolve {len(missing)} symbols: {missing[:10]}...")
    log.info(f"Resolved {len(keys)}/{len(symbols)} symbols to instrument keys")
    return keys


def snapshot_circuit_limits(
    engine,
    client: UpstoxRestClient,
    symbols: list[str],
    trade_date: date,
) -> int:
    """Fetch circuit limits from Upstox and store in DB."""
    instrument_keys = resolve_instrument_keys(symbols)
    if not instrument_keys:
        log.error("No instrument keys resolved")
        return 0

    all_records = []
    for i in range(0, len(instrument_keys), BATCH_SIZE):
        batch = instrument_keys[i : i + BATCH_SIZE]
        log.info(f"  Fetching batch {i // BATCH_SIZE + 1}: {len(batch)} instruments")
        try:
            quotes = client.get_quotes(batch)
        except Exception as e:
            log.error(f"  Batch failed: {e}")
            continue

        for key, data in quotes.items():
            if not isinstance(data, dict):
                continue
            # Extract symbol from key (format: "NSE_EQ:SYMBOL" or similar)
            parts = key.split(":")
            symbol = parts[-1] if len(parts) > 1 else key

            upper = float(data.get("upper_circuit_limit", 0) or 0)
            lower = float(data.get("lower_circuit_limit", 0) or 0)
            last_price = float(data.get("last_price", 0) or 0)

            if upper <= 0 and lower <= 0:
                continue

            # Calculate filter percentage from limits
            filter_pct = 0.0
            if last_price > 0 and upper > 0:
                filter_pct = round((upper / last_price - 1) * 100, 1)

            all_records.append(
                {
                    "symbol": symbol,
                    "exchange": "NSE",
                    "trade_date": str(trade_date),
                    "prev_close": last_price,
                    "upper_circuit": upper,
                    "lower_circuit": lower,
                    "filter_pct": filter_pct,
                    "source": "upstox_snapshot",
                }
            )

    # Upsert
    if all_records:
        with engine.begin() as conn:
            stmt = sa.text("""
                INSERT INTO stock_circuit_limits
                    (symbol, exchange, trade_date, prev_close, upper_circuit, lower_circuit, filter_pct, source)
                VALUES (:symbol, :exchange, :trade_date, :prev_close, :upper_circuit, :lower_circuit, :filter_pct, :source)
                ON CONFLICT (symbol, exchange, trade_date, source) DO UPDATE SET
                    prev_close = EXCLUDED.prev_close,
                    upper_circuit = EXCLUDED.upper_circuit,
                    lower_circuit = EXCLUDED.lower_circuit,
                    filter_pct = EXCLUDED.filter_pct
            """)
            for rec in all_records:
                conn.execute(stmt, rec)

    log.info(f"Snapshot: {len(all_records)} circuit limits stored")
    return len(all_records)


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot circuit limits from Upstox")
    parser.add_argument("--universe", default=None, help="Hypothesis name for universe")
    args = parser.parse_args()

    load_settings()
    engine = get_engine()

    # Resolve Upstox token
    from indian_quant.config.settings import UpstoxConfig

    uc = UpstoxConfig()
    token = uc.resolve_token()
    if not token:
        log.error("No Upstox access token found")
        return 1

    client = UpstoxRestClient(access_token=token)
    symbols = get_universe_symbols(engine, args.universe)
    log.info(f"Universe: {len(symbols)} symbols")

    today = date.today()
    n = snapshot_circuit_limits(engine, client, symbols, today)
    log.info(f"Done: {n} circuit limits snapshotted for {today}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
