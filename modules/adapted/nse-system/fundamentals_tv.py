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


"""
Fundamentals fetcher (canonical) — TradingView India scanner.
v5 (2026-09-12): rewritten after TV column probe. Uses only columns
that actually return values for NSE stocks.

Available on TV India (validated by tv_column_probe.py, 30 symbols):
  close, market_cap_basic, price_earnings_ttm,
  return_on_equity_fy, return_on_invested_capital_fy,
  debt_to_equity_fy, operating_margin_fy, net_margin_fy,
  gross_margin_fy, free_cash_flow_fy, capital_expenditures_fy,
  book_value_per_share_fy, earnings_per_share_fy,
  enterprise_value_ebitda_ttm, dividends_yield,
  beta_1_year, beta_3_year,
  total_shares_outstanding, float_shares_outstanding,
  average_volume_30d_calc

NOT available (returns null):
  revenue_growth_*, net_income_growth_*, eps_growth_*,
  price_to_book_*, held_percent_insiders,
  operating_cash_flow_fy

Derived:
  pb            = close / book_value_per_share_fy
  roic          = return_on_invested_capital_fy
  fcf_fy        = free_cash_flow_fy (raw)

TradingView's return_on_invested_capital field is stored as ROIC, not ROCE.
TradingView does not expose operating cash flow in this probe, so FCF is not
used as a CFO proxy.
"""
import datetime as dt
import sys
import time

import db
import universe_helper as U
from data_sources import ProviderFetchError, get_registry
from fundamentals_store import merge
from log_utils import get_logger

log = get_logger("fundamentals")

BATCH_SIZE = 100

COLUMNS = [
    "name",
    "close",
    "market_cap_basic",
    "price_earnings_ttm",
    "return_on_equity_fy",
    "return_on_invested_capital_fy",
    "debt_to_equity_fy",
    "operating_margin_fy",
    "net_margin_fy",
    "gross_margin_fy",
    "free_cash_flow_fy",
    "capital_expenditures_fy",
    "book_value_per_share_fy",
    "earnings_per_share_fy",
    "enterprise_value_ebitda_ttm",
    "dividends_yield",
    "beta_1_year",
    "beta_3_year",
    "total_shares_outstanding",
    "float_shares_outstanding",
    "average_volume_30d_calc",
]


def _fetch_batch(tickers, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            result = get_registry().fetch(
                "fundamentals.tv_batch",
                ("tradingview",),
                tickers=tickers,
                columns=COLUMNS,
                accept=lambda rows: bool(rows),
            )
            return result.data
        except Exception as e:
            last_err = e
            wait = 2 * (attempt + 1)
            log.warning(f"batch failed (attempt {attempt + 1}/{retries}): {e}; retrying in {wait}s")
            time.sleep(wait)
    log.error(f"batch failed permanently: {last_err}")
    raise ProviderFetchError("fundamentals.tv_batch", {"tradingview": str(last_err)}) from last_err


def _sector_map(conn):
    out = {}
    for s, sec in conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL"):
        out[s] = sec
    return out


def _universe(conn, limit=None):
    syms = {r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1")}
    syms |= set(U.band_universe(conn, 1500))
    out = sorted(syms)
    return out[:limit] if limit else out


def _fundamentals_values(sym, metrics, sectors, retrieved_at):
    close = metrics.get("close")
    bvps = metrics.get("book_value_per_share_fy")
    pb = (close / bvps) if (close is not None and bvps is not None and bvps > 0) else None
    mcap = metrics.get("market_cap_basic")
    return {
        "symbol": sym,
        "name": metrics.get("name"),
        "sector": sectors.get(sym),
        "current_price": close,
        "market_cap_cr": mcap / 1e7 if mcap is not None else None,
        "pe": metrics.get("price_earnings_ttm"),
        "pb": pb,
        "roe": metrics.get("return_on_equity_fy"),
        "roic": metrics.get("return_on_invested_capital_fy"),
        "debt_to_equity": metrics.get("debt_to_equity_fy"),
        "operating_margin": metrics.get("operating_margin_fy"),
        "net_profit_margin": metrics.get("net_margin_fy"),
        "dividend_yield": metrics.get("dividends_yield"),
        "beta_1y": metrics.get("beta_1_year"),
        "eps_fy": metrics.get("earnings_per_share_fy"),
        "book_value": bvps,
        "ev_ebitda": metrics.get("enterprise_value_ebitda_ttm"),
        "fcf_fy": metrics.get("free_cash_flow_fy"),
        "data_quality_flags": [
            "financial_period_end_unknown",
            "publication_time_unknown",
            "operating_cash_flow_unavailable",
        ],
        "source_metadata": {
            "source": "TradingView scanner",
            "retrieved_at": retrieved_at,
            "source_observation_date": None,
            "financial_period_end": None,
        },
    }


def run(limit=None):
    conn = db.get_conn()
    symbols = _universe(conn, limit)
    total = len(symbols)
    log.info(f"fundamentals fetch: {total} symbols, batch={BATCH_SIZE}")

    sectors = _sector_map(conn)
    now = "tv:" + dt.datetime.now().isoformat()
    saved = 0
    ok_batches = 0
    failed_batches = 0
    saved_fields = 0

    for b in range(0, total, BATCH_SIZE):
        batch = symbols[b : b + BATCH_SIZE]
        tickers = ["NSE:" + s for s in batch]
        try:
            data = _fetch_batch(tickers)
        except ProviderFetchError as exc:
            log.error(f"batch {b // BATCH_SIZE + 1} unavailable: {exc}")
            failed_batches += 1
            continue
        ok_batches += 1
        for item in data:
            sym = item["s"].replace("NSE:", "")
            d = item["d"]
            m = dict(zip(COLUMNS, d, strict=False))
            values = _fundamentals_values(sym, m, sectors, now[3:])

            merge(conn, values, source="tradingview", observed_at=now[3:])
            saved += 1
            # Count non-null core fields
            for k in ("roic", "roe", "pe", "debt_to_equity"):
                if values.get(k) is not None:
                    saved_fields += 1

        conn.commit()
        log.info(
            f"batch {b // BATCH_SIZE + 1} / "
            f"{(total + BATCH_SIZE - 1) // BATCH_SIZE}: "
            f"saved {saved} so far"
        )

    conn.close()
    log.info(
        f"fundamentals fetch complete: saved={saved} "
        f"batches_ok={ok_batches} batches_failed={failed_batches} "
        f"core_fields_populated={saved_fields}"
    )
    return saved


def count():
    conn = db.get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE data_source='tradingview'"
    ).fetchone()[0]
    n_roce = conn.execute("SELECT COUNT(*) FROM fundamentals WHERE roce IS NOT NULL").fetchone()[0]
    n_roe = conn.execute("SELECT COUNT(*) FROM fundamentals WHERE roe IS NOT NULL").fetchone()[0]
    n_pe = conn.execute("SELECT COUNT(*) FROM fundamentals WHERE pe IS NOT NULL").fetchone()[0]
    n_de = conn.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE debt_to_equity IS NOT NULL"
    ).fetchone()[0]
    n_cfo = conn.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE cfo_positive IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    log.info(
        f"fundamentals rows: {n} | "
        f"roce: {n_roce} | roe: {n_roe} | pe: {n_pe} | "
        f"debt_eq: {n_de} | cfo_flag: {n_cfo}"
    )
    return n


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else None
        run(limit=n)
        count()
    elif cmd == "count":
        count()
