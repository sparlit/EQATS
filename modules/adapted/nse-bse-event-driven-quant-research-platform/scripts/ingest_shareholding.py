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


"""Ingest institutional data: shareholding history + promoter pledge.

Uses BSE API for shareholding patterns, with MCP cascade fallback.
Populates shareholding_history and promoter_pledge tables.

Usage:
    python scripts/ingest_shareholding.py                 # full ingest
    python scripts/ingest_shareholding.py --symbol RELIANCE  # single stock
    python scripts/ingest_shareholding.py --limit 50      # first 50 stocks
"""


import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import sqlalchemy as sa
from indian_quant.config.connections import get_engine


def get_cached_signal_symbols(engine) -> list[str]:
    """Get all symbols from cached_signals that need institutional data."""
    df = pd.read_sql(
        "SELECT DISTINCT symbol FROM cached_signals WHERE signal_type IS NOT NULL ORDER BY symbol",
        engine,
    )
    return df["symbol"].tolist()


def resolve_bse_scripcode(symbol: str) -> str | None:
    """Resolve NSE symbol to BSE scrip code using bse library."""
    try:
        import tempfile

        from bse import BSE

        b = BSE(download_folder=tempfile.mkdtemp(prefix="bse_"))
        code = b.getScripCode(symbol)
        return str(code) if code else None
    except Exception:
        return None


def ingest_shareholding_from_bse(
    symbols: list[str],
    engine,
    delay: float = 0.5,
) -> int:
    """Ingest shareholding data from BSE API for given symbols.

    Returns number of stocks successfully ingested.
    """
    from indian_quant.ingestion.bse.shareholding import fetch_shareholding

    ingested = 0
    for sym in symbols:
        # Resolve BSE scrip code
        code = resolve_bse_scripcode(sym)
        if code is None:
            continue

        data = fetch_shareholding(code)
        if data is None:
            continue

        quarter = data.get("quarter", "")
        if not quarter:
            continue

        # Upsert shareholding_history
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                    INSERT INTO shareholding_history
                        (symbol, quarter, promoter_pct, fii_pct, dii_pct,
                         public_pct, promoter_chg, fii_chg, dii_chg, updated_at)
                    VALUES
                        (:symbol, :quarter, :promoter_pct, :fii_pct, :dii_pct,
                         :public_pct, :promoter_chg, :fii_chg, :dii_chg, NOW())
                    ON CONFLICT (symbol, quarter) DO UPDATE SET
                        promoter_pct = EXCLUDED.promoter_pct,
                        fii_pct = EXCLUDED.fii_pct,
                        dii_pct = EXCLUDED.dii_pct,
                        public_pct = EXCLUDED.public_pct,
                        promoter_chg = EXCLUDED.promoter_chg,
                        fii_chg = EXCLUDED.fii_chg,
                        dii_chg = EXCLUDED.dii_chg,
                        updated_at = NOW()
                """),
                {
                    "symbol": sym,
                    "quarter": quarter,
                    "promoter_pct": data.get("promoter_pct"),
                    "fii_pct": data.get("fii_pct"),
                    "dii_pct": data.get("dii_pct"),
                    "public_pct": data.get("public_pct"),
                    "promoter_chg": data.get("promoter_chg"),
                    "fii_chg": data.get("fii_chg"),
                    "dii_chg": data.get("dii_chg"),
                },
            )

            # Also update promoter_pledge if we have promoter data
            promoter_pct = data.get("promoter_pct")
            if promoter_pct is not None:
                risk = "LOW"
                if promoter_pct > 70:
                    risk = "MEDIUM"
                if promoter_pct > 85:
                    risk = "HIGH"

                conn.execute(
                    sa.text("""
                        INSERT INTO promoter_pledge
                            (symbol, pledge_pct, risk_signal, qoq_change, updated_at)
                        VALUES
                            (:symbol, :pledge_pct, :risk_signal, :chg, NOW())
                    ON CONFLICT (symbol) DO UPDATE SET
                        pledge_pct = EXCLUDED.pledge_pct,
                        risk_signal = EXCLUDED.risk_signal,
                        qoq_change = EXCLUDED.qoq_change,
                        updated_at = NOW()
                    """),
                    {
                        "symbol": sym,
                        "pledge_pct": None,
                        "risk_signal": risk,
                        "chg": data.get("promoter_chg"),
                    },
                )

        ingested += 1
        if ingested % 10 == 0:
            print(f"  {ingested}/{len(symbols)} ingested...")
        time.sleep(delay)

    return ingested


def ingest_from_mcp_fallback(engine) -> int:
    """Fallback: try MCP tools for shareholding data."""
    from indian_quant.ingestion.router import SourceRouter

    router = SourceRouter()
    symbols = get_cached_signal_symbols(engine)
    ingested = 0

    for sym in symbols:
        try:
            sh = router.get_shareholding(symbol=sym, exchange="NSE")
            if sh is None:
                continue

            # Parse MCP response
            quarter = sh.get("quarter", "")
            if not quarter:
                continue

            with engine.begin() as conn:
                conn.execute(
                    sa.text("""
                        INSERT INTO shareholding_history
                            (symbol, quarter, promoter_pct, fii_pct, dii_pct,
                             public_pct, promoter_chg, fii_chg, dii_chg, updated_at)
                        VALUES
                            (:symbol, :quarter, :promoter_pct, :fii_pct, :dii_pct,
                             :public_pct, :promoter_chg, :fii_chg, :dii_chg, NOW())
                        ON CONFLICT (symbol, quarter) DO UPDATE SET
                            promoter_pct = EXCLUDED.promoter_pct,
                            fii_pct = EXCLUDED.fii_pct,
                            dii_pct = EXCLUDED.dii_pct,
                            public_pct = EXCLUDED.public_pct,
                            promoter_chg = EXCLUDED.promoter_chg,
                            fii_chg = EXCLUDED.fii_chg,
                            dii_chg = EXCLUDED.dii_chg,
                            updated_at = NOW()
                    """),
                    {
                        "symbol": sym,
                        "quarter": quarter,
                        "promoter_pct": sh.get("promoter_pct"),
                        "fii_pct": sh.get("fii_pct"),
                        "dii_pct": sh.get("dii_pct"),
                        "public_pct": sh.get("public_pct"),
                        "promoter_chg": sh.get("promoter_chg"),
                        "fii_chg": sh.get("fii_chg"),
                        "dii_chg": sh.get("dii_chg"),
                    },
                )
            ingested += 1
        except Exception:
            continue

    return ingested


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest institutional shareholding data")
    parser.add_argument("--symbol", type=str, help="Single symbol to ingest")
    parser.add_argument("--limit", type=int, default=0, help="Max symbols to process (0=all)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between BSE API calls")
    args = parser.parse_args()

    engine = get_engine()

    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        symbols = get_cached_signal_symbols(engine)
        if args.limit > 0:
            symbols = symbols[: args.limit]

    print(f"Processing {len(symbols)} symbols...")

    # Try BSE API first
    print("Fetching from BSE API...")
    ingested = ingest_shareholding_from_bse(symbols, engine, delay=args.delay)
    print(f"BSE API: {ingested} stocks ingested")

    # Fallback to MCP if BSE got nothing
    if ingested == 0:
        print("BSE API returned nothing, trying MCP fallback...")
        ingested = ingest_from_mcp_fallback(engine)
        print(f"MCP fallback: {ingested} stocks ingested")

    # Report
    with engine.connect() as conn:
        sh_count = conn.execute(sa.text("SELECT COUNT(*) FROM shareholding_history")).scalar()
        pp_count = conn.execute(sa.text("SELECT COUNT(*) FROM promoter_pledge")).scalar()
    print(
        json.dumps(
            {
                "shareholding_history_rows": sh_count,
                "promoter_pledge_rows": pp_count,
                "symbols_processed": len(symbols),
                "successfully_ingested": ingested,
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
