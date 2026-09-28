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


"""Sector classification ingestion pipeline.

Fetches sector/industry data from FinStack, Indian Market MCP, or yfinance
and stores it in PostgreSQL.

Source tables: sector_map, sector_daily
"""


import logging
import time
from datetime import datetime

import sqlalchemy as sa

from indian_quant.config.connections import get_engine
from indian_quant.utils import safe_float

log = logging.getLogger(__name__)


def _fetch_sector(symbol: str) -> dict | None:
    """Fetch sector/industry for a symbol via cascade."""
    # 1. FinStack
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient

        client = FinStackClient()
        result = client.call_tool("company_profile", {"symbol": symbol})
        if result and isinstance(result, dict):
            sector = result.get("sector") or result.get("industry_sector")
            industry = result.get("industry") or result.get("industry_subsector")
            if sector:
                return {"sector": sector, "industry": industry}
    except Exception:
        pass

    # 2. Indian Market MCP
    try:
        from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient

        client = IndianMarketClient()
        result = client.call_tool("get_company_profile", {"symbol": symbol})
        if result and isinstance(result, dict):
            sector = result.get("sector")
            industry = result.get("industry")
            if sector:
                return {"sector": sector, "industry": industry}
    except Exception:
        pass

    # 3. yfinance
    try:
        import yfinance as yf

        for suffix in (".NS", ".BO"):
            try:
                ticker = yf.Ticker(f"{symbol}{suffix}")
                info = ticker.info
                sector = info.get("sector")
                if sector:
                    return {"sector": sector, "industry": info.get("industry")}
            except Exception:
                continue
    except Exception:
        pass

    return None


def _upsert_sector_map(engine, symbol: str, data: dict) -> None:
    """Store sector mapping."""
    values = {
        "symbol": symbol.upper(),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "updated_at": datetime.utcnow(),
    }
    cols = ", ".join(values.keys())
    phs = ", ".join(f":{k}" for k in values)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k != "symbol")
    sql = sa.text(f"INSERT INTO sector_map ({cols}) VALUES ({phs}) ON CONFLICT (symbol) DO UPDATE SET {updates}")
    with engine.begin() as conn:
        conn.execute(sql, values)


def _get_universe_symbols(engine) -> list[str]:
    """Get all symbols from cached_signals or instruments."""
    with engine.connect() as conn:
        try:
            result = conn.execute(sa.text("SELECT DISTINCT symbol FROM cached_signals ORDER BY symbol"))
            symbols = [r[0] for r in result.fetchall()]
            if symbols:
                return symbols
        except Exception:
            pass
        try:
            result = conn.execute(sa.text("SELECT symbol FROM instruments ORDER BY symbol"))
            return [r[0] for r in result.fetchall()]
        except Exception:
            pass
    return []


def ingest_sectors(symbol: str, *, engine=None) -> bool:
    """Ingest sector classification for a single symbol.

    Returns True if sector data was found and stored.
    """
    engine = engine or get_engine()
    data = _fetch_sector(symbol.upper())
    if data:
        _upsert_sector_map(engine, symbol.upper(), data)
        return True
    return False


def ingest_all_sectors(
    *,
    batch_size: int = 50,
    sleep: float = 1.0,
) -> dict:
    """Batch sector ingestion for all symbols.

    Returns:
        {"success": N, "failed": N, "total": N}
    """
    engine = get_engine()
    symbols = _get_universe_symbols(engine)
    if not symbols:
        log.error("No symbols found. Run cache_signals.py first.")
        return {"success": 0, "failed": 0, "total": 0}

    log.info(f"Ingesting sectors for {len(symbols)} symbols")
    start = time.time()
    success = failed = 0

    for i, symbol in enumerate(symbols):
        try:
            ok = ingest_sectors(symbol, engine=engine)
            if ok:
                success += 1
            else:
                failed += 1
        except KeyboardInterrupt:
            log.info("Interrupted.")
            break
        except Exception as e:
            log.warning(f"Error processing {symbol}: {e}")
            failed += 1

        if (i + 1) % batch_size == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(symbols) - i - 1) / rate if rate > 0 else 0
            log.info(f"  [{i + 1}/{len(symbols)}] success={success} failed={failed} rate={rate:.1f}/s ETA={eta:.0f}s")
            time.sleep(sleep)

    elapsed = time.time() - start
    log.info(f"Done in {elapsed:.1f}s: {success} success, {failed} failed out of {len(symbols)}")
    return {"success": success, "failed": failed, "total": len(symbols)}
