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
"""Compute per-stock and portfolio risk metrics.

Per-stock: beta, volatility, VaR, max drawdown, correlation to Nifty
Portfolio: VaR, CVaR, concentration, drawdown

Usage:
    python scripts/compute_risk.py                # Full universe
    python scripts/compute_risk.py --portfolio    # Portfolio risk only
    python scripts/compute_risk.py --symbol RELIANCE  # Single stock
"""


import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import sqlalchemy as sa
from indian_quant.web.prod_config import get_pg_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("compute_risk")

TRADING_DAYS = 252


def load_price_history(symbol: str, days: int = 252) -> pd.Series | None:
    """Load close price history for a symbol."""
    parquet = Path(f"data/normalized/bars_1d/NSE/{symbol}.parquet")
    if not parquet.exists():
        return None
    try:
        df = pd.read_parquet(parquet)
        # Support both old ('date') and new ('timestamp') column names
        date_col = "date" if "date" in df.columns else "timestamp"
        close_col = "close"
        if date_col not in df.columns or close_col not in df.columns:
            return None
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col).tail(days)
        if len(df) < 30:
            return None
        return df.set_index(date_col)[close_col]
    except Exception:
        return None


def load_nifty_history(days: int = 252) -> pd.Series | None:
    """Load Nifty 50 index history for beta/correlation."""
    # Try multiple sources
    for path in ["data/normalized/bars_1d/NSE/NIFTY_50.parquet", "data/normalized/bars_1d/NSE/NIFTY50.parquet"]:
        p = Path(path)
        if p.exists():
            try:
                df = pd.read_parquet(p)
                date_col = "date" if "date" in df.columns else "timestamp"
                if date_col not in df.columns or "close" not in df.columns:
                    continue
                df[date_col] = pd.to_datetime(df[date_col])
                df = df.sort_values(date_col).tail(days)
                return df.set_index(date_col)["close"]
            except Exception:
                continue

    # Fallback: yfinance
    try:
        import yfinance as yf

        nifty = yf.Ticker("^NSEI")
        df = nifty.history(period="1y")
        if len(df) > 30:
            return df["Close"]
    except Exception:
        pass
    return None


def compute_stock_risk(symbol: str, prices: pd.Series, nifty: pd.Series | None) -> dict | None:
    """Compute risk metrics for a single stock."""
    if len(prices) < 30:
        return None

    returns = prices.pct_change().dropna()
    if len(returns) < 20:
        return None

    # Volatility
    vol_30d = returns.tail(30).std() * np.sqrt(TRADING_DAYS)
    vol_annual = returns.std() * np.sqrt(TRADING_DAYS)

    # VaR (95% and 99%)
    var_95 = returns.quantile(0.05)
    returns.quantile(0.01)

    # Max drawdown (1 year)
    cummax = (1 + returns).cumprod().cummax()
    drawdown = (1 + returns).cumprod() / cummax - 1
    max_dd = drawdown.min()

    # Beta and correlation to Nifty
    beta = None
    corr_nifty = None
    if nifty is not None and len(nifty) > 30:
        nifty_returns = nifty.pct_change().dropna()
        # Align dates
        common_dates = returns.index.intersection(nifty_returns.index)
        if len(common_dates) >= 20:
            stock_ret = returns.loc[common_dates]
            nifty_ret = nifty_returns.loc[common_dates]
            cov = np.cov(stock_ret, nifty_ret)
            var_nifty = cov[1, 1]
            if var_nifty > 0:
                beta = cov[0, 1] / var_nifty
            corr_nifty = np.corrcoef(stock_ret, nifty_ret)[0, 1]

    # Average daily volume and turnover
    avg_volume = None
    avg_turnover = None
    try:
        parquet = Path(f"data/normalized/bars_1d/NSE/{symbol}.parquet")
        df = pd.read_parquet(parquet, columns=["date", "close", "volume"])
        df = df.tail(30)
        avg_volume = int(df["volume"].mean()) if "volume" in df.columns else None
        avg_turnover = (df["close"] * df["volume"]).mean() / 1e7 if avg_volume else None  # in Cr
    except Exception:
        pass

    # Impact cost estimate (simplified: based on avg daily volume)
    impact_cost = None
    if avg_volume and avg_volume > 0:
        # Rough estimate: ₹5L order / avg daily volume * 100
        order_value = 5_00_000  # 5 lakhs
        participation = order_value / (avg_volume * 100) if avg_volume > 0 else 1
        impact_cost = min(participation * 50000, 100000)  # cap at ₹1L

    return {
        "symbol": symbol,
        "beta": round(beta, 4) if beta is not None else None,
        "vol_30d": round(float(vol_30d), 4),
        "vol_annual": round(float(vol_annual), 4),
        "var_95": round(float(var_95), 6),
        "max_drawdown_1y": round(float(max_dd), 6),
        "correlation_nifty": round(float(corr_nifty), 4) if corr_nifty is not None else None,
        "avg_daily_volume": avg_volume,
        "avg_turnover": round(float(avg_turnover), 2) if avg_turnover is not None else None,
        "impact_cost": round(float(impact_cost), 0) if impact_cost is not None else None,
    }


def upsert_stock_risk(engine, data: dict) -> None:
    """Store stock risk metrics."""
    data["updated_at"] = datetime.utcnow()
    cols = ", ".join(data.keys())
    phs = ", ".join(f":{k}" for k in data)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in data if k != "symbol")
    sql = sa.text(f"INSERT INTO stock_risk ({cols}) VALUES ({phs}) ON CONFLICT (symbol) DO UPDATE SET {updates}")
    with engine.begin() as conn:
        conn.execute(sql, data)


def compute_portfolio_risk(engine) -> dict | None:
    """Compute portfolio-level risk metrics from open paper trades."""
    # Get open positions from PostgreSQL
    with engine.connect() as conn:
        rows = (
            conn.execute(
                sa.text(
                    "SELECT symbol, close_at_signal, qty, horizon_label, stop_pct FROM paper_signals WHERE status = 'OPEN'"
                )
            )
            .mappings()
            .fetchall()
        )
        positions = [dict(r) for r in rows]

    if not positions:
        return None

    total_value = sum(p["close_at_signal"] * p["qty"] for p in positions)
    if total_value <= 0:
        return None

    # Load returns for each position
    all_returns = {}
    for pos in positions:
        prices = load_price_history(pos["symbol"])
        if prices is not None and len(prices) > 20:
            rets = prices.pct_change().dropna().tail(30)
            all_returns[pos["symbol"]] = rets

    if len(all_returns) < 2:
        return None

    # Build returns matrix
    returns_df = pd.DataFrame(all_returns)
    returns_df = returns_df.dropna(how="all")

    if len(returns_df) < 10:
        return None

    # Portfolio weights
    weights = {}
    for pos in positions:
        w = (pos["close_at_signal"] * pos["qty"]) / total_value
        weights[pos["symbol"]] = weights.get(pos["symbol"], 0) + w

    # Weighted portfolio returns
    portfolio_returns = pd.Series(0.0, index=returns_df.index)
    for col in returns_df.columns:
        if col in weights:
            portfolio_returns += returns_df[col].fillna(0) * weights[col]

    # VaR and CVaR
    var_95 = float(portfolio_returns.quantile(0.05))
    var_99 = float(portfolio_returns.quantile(0.01))
    cvar_95 = (
        float(portfolio_returns[portfolio_returns <= var_95].mean())
        if len(portfolio_returns[portfolio_returns <= var_95]) > 0
        else var_95
    )

    # Portfolio beta (weighted average)
    portfolio_beta = None
    nifty = load_nifty_history()
    if nifty is not None:
        nifty_rets = nifty.pct_change().dropna()
        common = returns_df.index.intersection(nifty_rets.index)
        if len(common) >= 10:
            port_in_common = portfolio_returns.loc[common]
            nifty_in_common = nifty_rets.loc[common]
            cov = np.cov(port_in_common, nifty_in_common)
            if cov[1, 1] > 0:
                portfolio_beta = round(float(cov[0, 1] / cov[1, 1]), 4)

    # Max drawdown
    cummax = (1 + portfolio_returns).cumprod().cummax()
    drawdown = (1 + portfolio_returns).cumprod() / cummax - 1
    max_dd = float(drawdown.min())

    # Sharpe ratio (30-day)
    sharpe = (
        float(portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(TRADING_DAYS))
        if portfolio_returns.std() > 0
        else 0
    )

    # Concentration (HHI)
    sector_weights = {}
    for pos in positions:
        sector = "Unknown"  # Would need sector_map lookup
        sector_weights[sector] = sector_weights.get(sector, 0) + weights.get(pos["symbol"], 0)
    hhi = sum(w**2 for w in sector_weights.values())

    n_sectors = len(sector_weights)
    top_sector_pct = max(sector_weights.values()) if sector_weights else 0

    return {
        "snapshot_date": datetime.utcnow().date(),
        "total_value": int(total_value),
        "var_95": round(var_95, 6),
        "var_99": round(var_99, 6),
        "cvar_95": round(cvar_95, 6),
        "portfolio_beta": portfolio_beta,
        "max_drawdown": round(max_dd, 6),
        "sharpe_ratio": round(sharpe, 4),
        "concentration_hhi": round(hhi, 4),
        "n_positions": len(positions),
        "n_sectors": n_sectors,
        "top_sector_pct": round(top_sector_pct, 4),
    }


def upsert_portfolio_risk(engine, data: dict) -> None:
    """Store portfolio risk snapshot."""
    data["updated_at"] = datetime.utcnow()
    cols = ", ".join(data.keys())
    phs = ", ".join(f":{k}" for k in data)
    updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in data if k != "snapshot_date")
    sql = sa.text(
        f"INSERT INTO portfolio_risk ({cols}) VALUES ({phs}) ON CONFLICT (snapshot_date) DO UPDATE SET {updates}"
    )
    with engine.begin() as conn:
        conn.execute(sql, data)


def main():
    parser = argparse.ArgumentParser(description="Compute risk metrics")
    parser.add_argument("--symbol", help="Single symbol")
    parser.add_argument("--portfolio", action="store_true", help="Portfolio risk only")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    engine = get_pg_engine()
    start = time.time()

    # Portfolio risk
    if args.portfolio or not args.symbol:
        log.info("Computing portfolio risk...")
        port_risk = compute_portfolio_risk(engine)
        if port_risk:
            upsert_portfolio_risk(engine, port_risk)
            log.info(
                f"  Portfolio: VaR95={port_risk['var_95']:.4f} "
                f"CVaR95={port_risk['cvar_95']:.4f} "
                f"Beta={port_risk.get('portfolio_beta', 'N/A')} "
                f"MaxDD={port_risk['max_drawdown']:.4f} "
                f"Sharpe={port_risk['sharpe_ratio']:.2f}"
            )
        else:
            log.warning("  No open positions or insufficient data")

    if args.portfolio:
        elapsed = time.time() - start
        log.info(f"Done in {elapsed:.1f}s")
        return

    # Stock risk
    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        with engine.connect() as conn:
            result = conn.execute(sa.text("SELECT DISTINCT symbol FROM cached_signals WHERE exchange = 'NSE'"))
            symbols = [r[0] for r in result.fetchall()]

    log.info(f"Computing stock risk for {len(symbols)} symbols...")
    nifty = load_nifty_history()
    success = 0

    for i, symbol in enumerate(symbols):
        try:
            prices = load_price_history(symbol)
            if prices is None:
                continue

            risk = compute_stock_risk(symbol, prices, nifty)
            if risk:
                upsert_stock_risk(engine, risk)
                success += 1

            if (i + 1) % args.batch_size == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                log.info(f"  [{i + 1}/{len(symbols)}] success={success} rate={rate:.1f}/s")
                time.sleep(args.sleep)

        except KeyboardInterrupt:
            log.info("Interrupted.")
            break
        except Exception as e:
            log.debug(f"Error processing {symbol}: {e}")

    elapsed = time.time() - start
    log.info(f"\nDone in {elapsed:.1f}s: {success} stocks processed")


if __name__ == "__main__":
    main()
