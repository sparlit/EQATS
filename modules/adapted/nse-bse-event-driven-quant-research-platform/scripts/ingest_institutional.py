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


#!/usr/bin/env python3
"""Ingest institutional flow data into PostgreSQL.

Covers: FII/DII daily flows, shareholding patterns, bulk deals, insider trades, promoter pledge.

Usage:
    python scripts/ingest_institutional.py --daily       # FII/DII + bulk deals (daily)
    python scripts/ingest_institutional.py --shareholding # Shareholding patterns (weekly)
    python scripts/ingest_institutional.py --all          # Everything
    python scripts/ingest_institutional.py --symbol RELIANCE  # Single stock shareholding
"""


import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa
from indian_quant.web.prod_config import get_pg_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_institutional")


from indian_quant.utils import safe_float as _safe_float
from indian_quant.utils import safe_int as _safe_int

# ── FII/DII Daily Flows ──


def fetch_fii_dii() -> list[dict] | None:
    """Fetch FII/DII data from FinStack."""
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient

        client = FinStackClient()
        result = client.call_tool("nse_fii_dii_data", {})
        if result and isinstance(result, dict):
            return result.get("data", [])
    except Exception as e:
        log.warning(f"FinStack FII/DII failed: {e}")
    return None


def upsert_fii_dii_daily(engine, data: list[dict]) -> int:
    """Store FII/DII daily data. Returns count of rows inserted."""
    count = 0
    for entry in data:
        try:
            # NSE API format varies; try common field names
            trade_date = entry.get("date") or entry.get("trade_date") or entry.get("trdDate")
            if not trade_date:
                continue

            # Parse date
            if isinstance(trade_date, str):
                for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        trade_date = datetime.strptime(trade_date, fmt).date()
                        break
                    except ValueError:
                        continue
                if isinstance(trade_date, str):
                    continue

            # Extract values - NSE format has category-based fields
            fii_buy = _safe_int(entry.get("fiiBuyValue") or entry.get("fii_buy"))
            fii_sell = _safe_int(entry.get("fiiSellValue") or entry.get("fii_sell"))
            dii_buy = _safe_int(entry.get("diiBuyValue") or entry.get("dii_buy"))
            dii_sell = _safe_int(entry.get("diiSellValue") or entry.get("dii_sell"))

            if fii_buy is None and fii_sell is None:
                continue

            fii_net = (fii_buy or 0) - (fii_sell or 0)
            dii_net = (dii_buy or 0) - (dii_sell or 0)
            fii_total = (fii_buy or 0) + (fii_sell or 0)
            dii_total = (dii_buy or 0) + (dii_sell or 0)

            values = {
                "trade_date": trade_date,
                "fii_buy": fii_buy,
                "fii_sell": fii_sell,
                "fii_net": fii_net,
                "dii_buy": dii_buy,
                "dii_sell": dii_sell,
                "dii_net": dii_net,
                "fii_net_pct": (fii_net / fii_total * 100) if fii_total > 0 else None,
                "dii_net_pct": (dii_net / dii_total * 100) if dii_total > 0 else None,
                "fii_dii_ratio": (fii_net / dii_net) if dii_net != 0 else None,
                "updated_at": datetime.utcnow(),
            }

            cols = ", ".join(values.keys())
            phs = ", ".join(f":{k}" for k in values)
            updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k != "trade_date")
            sql = sa.text(
                f"INSERT INTO fii_dii_daily ({cols}) VALUES ({phs}) "
                f"ON CONFLICT (trade_date) DO UPDATE SET {updates}"
            )
            with engine.begin() as conn:
                conn.execute(sql, values)
            count += 1
        except Exception as e:
            log.debug(f"Error processing FII/DII entry: {e}")
    return count


# ── Shareholding Patterns ──


def fetch_shareholding(symbol: str) -> dict | None:
    """Fetch shareholding pattern for a symbol."""
    # 1. FinStack
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient

        client = FinStackClient()
        result = client.call_tool("promoter_shareholding", {"symbol": symbol})
        if result and isinstance(result, dict) and result.get("shareholding_pattern"):
            return _parse_finstack_shareholding(symbol, result)
    except Exception:
        pass

    # 2. Indian Market MCP
    try:
        from indian_quant.ingestion.mcp.indian_market_client import IndianMarketClient

        client = IndianMarketClient()
        result = client.call_tool("get_shareholding_pattern", {"symbol": symbol})
        if result and isinstance(result, dict):
            return _parse_indian_market_shareholding(symbol, result)
    except Exception:
        pass

    return None


def _parse_finstack_shareholding(symbol: str, data: dict) -> dict | None:
    """Parse FinStack shareholding format."""
    pattern = data.get("shareholding_pattern", [])
    if not pattern:
        return None

    # Get latest quarter
    latest = pattern[0] if pattern else {}
    quarter = latest.get("quarter", "")

    result = {"symbol": symbol, "quarter": quarter}
    for entry in pattern:
        cat = (entry.get("category") or "").lower()
        pct = _safe_float(entry.get("pct_total"))
        if "promoter" in cat:
            result["promoter_pct"] = pct
        elif "fii" in cat or "foreign" in cat:
            result["fii_pct"] = pct
        elif "dii" in cat or "mutual" in cat or "insurance" in cat:
            result["dii_pct"] = pct
        elif "public" in cat or "retail" in cat:
            result["public_pct"] = pct

    return result if result.get("promoter_pct") is not None else None


def _parse_indian_market_shareholding(symbol: str, data: dict) -> dict | None:
    """Parse Indian Market MCP shareholding format."""
    # Could be nested or flat depending on version
    pattern = data.get("shareholding_pattern") or data.get("data") or []
    if isinstance(data, dict) and "promoter" in data:
        # Flat format
        return {
            "symbol": symbol,
            "quarter": data.get("quarter", ""),
            "promoter_pct": _safe_float(data.get("promoter")),
            "fii_pct": _safe_float(data.get("fii") or data.get("FII")),
            "dii_pct": _safe_float(data.get("dii") or data.get("DII")),
            "public_pct": _safe_float(data.get("public") or data.get("retail")),
        }
    if isinstance(pattern, list) and pattern:
        return _parse_finstack_shareholding(symbol, {"shareholding_pattern": pattern})
    return None


def upsert_shareholding(engine, data: dict) -> None:
    """Store shareholding pattern."""
    if not data or not data.get("quarter"):
        return
    values = {
        "symbol": data["symbol"],
        "quarter": data["quarter"],
        "promoter_pct": data.get("promoter_pct"),
        "fii_pct": data.get("fii_pct"),
        "dii_pct": data.get("dii_pct"),
        "public_pct": data.get("public_pct"),
        "promoter_chg": data.get("promoter_chg"),
        "fii_chg": data.get("fii_chg"),
        "dii_chg": data.get("dii_chg"),
        "updated_at": datetime.utcnow(),
    }
    cols = ", ".join(values.keys())
    phs = ", ".join(f":{k}" for k in values)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k not in ("symbol", "quarter"))
    sql = sa.text(
        f"INSERT INTO shareholding_history ({cols}) VALUES ({phs}) "
        f"ON CONFLICT (symbol, quarter) DO UPDATE SET {updates}"
    )
    with engine.begin() as conn:
        conn.execute(sql, values)


# ── Bulk Deals ──


def fetch_bulk_deals() -> list[dict] | None:
    """Fetch bulk deals from FinStack."""
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient

        client = FinStackClient()
        result = client.call_tool("nse_bulk_deals", {})
        if result and isinstance(result, dict):
            return result.get("data", [])
    except Exception as e:
        log.warning(f"FinStack bulk deals failed: {e}")
    return None


def upsert_bulk_deals(engine, data: list[dict]) -> int:
    """Store bulk deals. Returns count."""
    count = 0
    for entry in data:
        try:
            deal_date = entry.get("date") or entry.get("trade_date")
            if not deal_date:
                continue
            if isinstance(deal_date, str):
                for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
                    try:
                        deal_date = datetime.strptime(deal_date, fmt).date()
                        break
                    except ValueError:
                        continue
                if isinstance(deal_date, str):
                    continue

            symbol = entry.get("symbol") or entry.get("scrip")
            client_name = entry.get("client") or entry.get("client_name")
            if not symbol or not client_name:
                continue

            deal_type = "BUY" if "buy" in str(entry.get("deal_type", "")).lower() else "SELL"
            qty = _safe_int(entry.get("quantity") or entry.get("qty"))
            price = _safe_float(entry.get("price") or entry.get("avg_price"))
            value = _safe_int(entry.get("value") or entry.get("deal_value"))

            values = {
                "deal_date": deal_date,
                "symbol": symbol.upper(),
                "client": client_name,
                "deal_type": deal_type,
                "quantity": qty,
                "price": price,
                "value": value,
                "updated_at": datetime.utcnow(),
            }
            cols = ", ".join(values.keys())
            phs = ", ".join(f":{k}" for k in values)
            sql = sa.text(
                f"INSERT INTO bulk_deals ({cols}) VALUES ({phs}) "
                f"ON CONFLICT (deal_date, symbol, client) DO NOTHING"
            )
            with engine.begin() as conn:
                conn.execute(sql, values)
            count += 1
        except Exception as e:
            log.debug(f"Error processing bulk deal: {e}")
    return count


# ── Insider Trades ──


def fetch_insider_trades(symbol: str, days: int = 90) -> list[dict] | None:
    """Fetch insider trades (SAST disclosures) from FinStack."""
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient

        client = FinStackClient()
        result = client.call_tool("nse_insider_trading", {"symbol": symbol, "days": days})
        if result and isinstance(result, dict):
            return result.get("data", result.get("disclosures", []))
    except Exception:
        pass
    return None


def upsert_insider_trades(engine, symbol: str, data: list[dict]) -> int:
    """Store insider trades. Returns count."""
    count = 0
    for entry in data:
        try:
            trade_date = entry.get("trade_date") or entry.get("date")
            if not trade_date:
                continue
            if isinstance(trade_date, str):
                for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        trade_date = datetime.strptime(trade_date, fmt).date()
                        break
                    except ValueError:
                        continue
                if isinstance(trade_date, str):
                    continue

            insider_name = (
                entry.get("insider_name") or entry.get("acquirer_name") or entry.get("name")
            )
            if not insider_name:
                continue

            values = {
                "symbol": symbol.upper(),
                "trade_date": trade_date,
                "insider_name": insider_name,
                "transaction_type": entry.get("transaction_type") or entry.get("mode"),
                "shares_traded": _safe_int(entry.get("shares_traded") or entry.get("shares")),
                "shares_after": _safe_int(entry.get("shares_after") or entry.get("total_holdings")),
                "reported_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            cols = ", ".join(values.keys())
            phs = ", ".join(f":{k}" for k in values)
            sql = sa.text(
                f"INSERT INTO insider_trades ({cols}) VALUES ({phs}) "
                f"ON CONFLICT (symbol, trade_date, insider_name) DO NOTHING"
            )
            with engine.begin() as conn:
                conn.execute(sql, values)
            count += 1
        except Exception as e:
            log.debug(f"Error processing insider trade: {e}")
    return count


# ── Promoter Pledge ──


def fetch_promoter_pledge(symbol: str) -> dict | None:
    """Fetch promoter pledge data from FinStack."""
    try:
        from indian_quant.ingestion.mcp.finstack_client import FinStackClient

        client = FinStackClient()
        result = client.call_tool("promoter_pledge", {"symbol": symbol})
        if result and isinstance(result, dict):
            return result
    except Exception:
        pass
    return None


def upsert_promoter_pledge(engine, symbol: str, data: dict) -> None:
    """Store promoter pledge data."""
    if not data:
        return
    values = {
        "symbol": symbol.upper(),
        "pledge_pct": _safe_float(data.get("pledge_pct") or data.get("pledged_percentage")),
        "risk_signal": data.get("risk_signal") or data.get("risk"),
        "qoq_change": _safe_float(data.get("qoq_change")),
        "updated_at": datetime.utcnow(),
    }
    cols = ", ".join(values.keys())
    phs = ", ".join(f":{k}" for k in values)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in values if k != "symbol")
    sql = sa.text(
        f"INSERT INTO promoter_pledge ({cols}) VALUES ({phs}) "
        f"ON CONFLICT (symbol) DO UPDATE SET {updates}"
    )
    with engine.begin() as conn:
        conn.execute(sql, values)


def get_universe_symbols(engine) -> list[str]:
    """Get all NSE symbols."""
    with engine.connect() as conn:
        try:
            result = conn.execute(
                sa.text(
                    "SELECT DISTINCT symbol FROM cached_signals WHERE exchange = 'NSE' ORDER BY symbol"
                )
            )
            return [r[0] for r in result.fetchall()]
        except Exception:
            pass
        try:
            result = conn.execute(
                sa.text("SELECT symbol FROM instruments WHERE exchange = 'NSE' ORDER BY symbol")
            )
            return [r[0] for r in result.fetchall()]
        except Exception:
            pass
    return []


def main():
    parser = argparse.ArgumentParser(description="Ingest institutional flow data")
    parser.add_argument("--daily", action="store_true", help="FII/DII + bulk deals (daily)")
    parser.add_argument(
        "--shareholding", action="store_true", help="Shareholding patterns (weekly)"
    )
    parser.add_argument("--insiders", action="store_true", help="Insider trades (weekly)")
    parser.add_argument("--pledge", action="store_true", help="Promoter pledge (weekly)")
    parser.add_argument("--all", action="store_true", help="Everything")
    parser.add_argument("--symbol", help="Single symbol for shareholding/insiders/pledge")
    parser.add_argument("--symbols", nargs="+", help="List of symbols")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    engine = get_pg_engine()
    do_all = args.all

    start = time.time()

    # ── FII/DII Daily ──
    if do_all or args.daily:
        log.info("Fetching FII/DII daily data...")
        fii_dii = fetch_fii_dii()
        if fii_dii:
            count = upsert_fii_dii_daily(engine, fii_dii)
            log.info(f"  FII/DII: {count} days stored")
        else:
            log.warning("  FII/DII: no data available")

    # ── Bulk Deals ──
    if do_all or args.daily:
        log.info("Fetching bulk deals...")
        deals = fetch_bulk_deals()
        if deals:
            count = upsert_bulk_deals(engine, deals)
            log.info(f"  Bulk deals: {count} entries stored")
        else:
            log.warning("  Bulk deals: no data available")

    # ── Per-stock data (shareholding, insiders, pledge) ──
    if do_all or args.shareholding or args.insiders or args.pledge:
        if args.symbol:
            symbols = [args.symbol.upper()]
        elif args.symbols:
            symbols = [s.upper() for s in args.symbols]
        else:
            symbols = get_universe_symbols(engine)

        log.info(f"Processing per-stock data for {len(symbols)} symbols...")
        success = 0
        failed = 0

        for i, symbol in enumerate(symbols):
            try:
                # Shareholding
                if do_all or args.shareholding:
                    sh = fetch_shareholding(symbol)
                    if sh:
                        upsert_shareholding(engine, sh)
                        success += 1
                    else:
                        failed += 1

                # Insider trades
                if do_all or args.insiders:
                    insiders = fetch_insider_trades(symbol)
                    if insiders:
                        upsert_insider_trades(engine, symbol, insiders)

                # Promoter pledge
                if do_all or args.pledge:
                    pledge = fetch_promoter_pledge(symbol)
                    if pledge:
                        upsert_promoter_pledge(engine, symbol, pledge)

                if (i + 1) % args.batch_size == 0:
                    elapsed = time.time() - start
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    log.info(
                        f"  [{i + 1}/{len(symbols)}] success={success} failed={failed} rate={rate:.1f}/s"
                    )
                    time.sleep(args.sleep)

            except KeyboardInterrupt:
                log.info("Interrupted.")
                break
            except Exception as e:
                log.warning(f"Error processing {symbol}: {e}")
                failed += 1

    elapsed = time.time() - start
    log.info(f"\nDone in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
