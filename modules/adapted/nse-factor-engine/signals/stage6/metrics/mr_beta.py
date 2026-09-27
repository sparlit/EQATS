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
Stage 6 — Beta Calculator

Computes 12-month beta for:
  1. Individual stocks in portfolio (vs Nifty500 daily returns)
  2. Portfolio-level beta (equal-weighted portfolio return series vs Nifty500)

Per stock output:
  beta_12m, cov, bench_var, stock_12m_ret, market_12m_ret, alpha_12m (Jensen)

Portfolio output:
  portfolio_beta, portfolio_12m_ret, market_12m_ret

Jensen Alpha = Stock 12m - Rf - Beta * (Market 12m - Rf)
Rf = 7% annualised

Data sources:
  - Stock prices : /home/ec2-user/nse-factor-engine/data/prices.parquet
  - Index prices : /home/ec2-user/nse-factor-engine/data/index_prices_*.parquet
  - Nifty500 sym : ^CRSLDX
"""

import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

NIFTY500_SYMBOL = "^CRSLDX"
PRICES_PATH = Path("/home/ec2-user/nse-factor-engine/data/prices.parquet")
INDEX_DIR = Path("/home/ec2-user/nse-factor-engine/data")
BETA_WINDOW = 252  # ~12 months of trading days
RF_ANNUAL = 0.07  # risk-free rate annualised


def _latest_index_file(index_dir: Path) -> Path:
    """Return most recent index_prices_DDMMYYYY.parquet by parsed date."""
    files = list(index_dir.glob("index_prices_*.parquet"))
    assert files, f"No index_prices_*.parquet found in {index_dir}"

    def parse_date(f):
        m = re.search(r"index_prices_(\d{2})(\d{2})(\d{4})\.parquet", f.name)
        assert m, f"Unexpected filename format: {f.name}"
        dd, mm, yyyy = m.groups()
        return datetime(int(yyyy), int(mm), int(dd))

    return max(files, key=parse_date)


def _load_nifty500() -> pd.Series:
    """Load Nifty500 daily close prices, return as date-indexed Series."""
    idx = pd.read_parquet(_latest_index_file(INDEX_DIR))
    n500 = idx[idx["symbol"] == NIFTY500_SYMBOL].copy().sort_values("date").set_index("date")["close"]
    assert len(n500) > 0, f"{NIFTY500_SYMBOL} not found in index file"
    return n500


def _strip_suffix(symbol: str) -> str:
    """Strip .NS or .BO suffix from symbol if present."""
    for suffix in [".NS", ".BO"]:
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)]
    return symbol


def _load_stock_prices(symbols: list) -> pd.DataFrame:
    """Load daily close prices for given symbols, return wide DataFrame.
    Handles .NS/.BO suffix mismatch. Returns original symbol names as columns.
    """
    px = pd.read_parquet(PRICES_PATH)
    all_px_syms = set(px["symbol"].unique())

    sym_map = {}
    for s in symbols:
        stripped = _strip_suffix(s)
        if s in all_px_syms:
            sym_map[s] = s
        elif stripped in all_px_syms:
            sym_map[s] = stripped

    px_syms = list(set(sym_map.values()))
    px = px[px["symbol"].isin(px_syms)].copy()
    wide = px.pivot(index="date", columns="symbol", values="close")

    reverse_map = {v: k for k, v in sym_map.items()}
    wide = wide.rename(columns=reverse_map)
    return wide.sort_index()


def _compute_single_beta(ret_stock: pd.Series, ret_bench: pd.Series) -> tuple:
    """
    Returns (beta, cov, bench_var) for a stock vs benchmark return series.
    Returns (nan, nan, nan) if insufficient data.
    """
    aln = pd.concat([ret_stock, ret_bench], axis=1).dropna()
    if len(aln) < 20:
        return np.nan, np.nan, np.nan
    aln.columns = ["stock", "bench"]
    cov = aln["stock"].cov(aln["bench"])
    bench_var = aln["bench"].var()
    beta = cov / bench_var if bench_var > 0 else np.nan
    return beta, cov, bench_var


def compute_beta(top25_symbols: set, as_of_date: pd.Timestamp, portfolio_symbols: set | None = None) -> dict:
    """
    Compute 12-month beta, returns, covariance and Jensen alpha
    for each stock in top25 and for the equal-weighted portfolio.

    Parameters
    ----------
    top25_symbols     : set of symbol strings — per-stock beta computed for all
    as_of_date        : rebalance date (signal Friday)
    portfolio_symbols : optional subset for portfolio-level beta (default = top25_symbols)
                        Pass top25_symbols explicitly in monitor mode to exclude SELLs.

    Returns
    -------
    dict with keys:
        stocks          : list of per-stock dicts
        portfolio_beta  : float
        portfolio_12m_ret : float
        market_12m_ret  : float
        bench_start     : date
        bench_end       : date
        n_obs           : int
    """
    print(f"\nComputing 12-month beta as of {as_of_date.date()} ...")

    # ── Load Nifty500 ──────────────────────────────────────────────────────────
    n500 = _load_nifty500()
    n500_ret = n500.pct_change(fill_method=None).dropna()
    n500_ret = n500_ret[n500_ret.index <= as_of_date].tail(BETA_WINDOW)

    if len(n500_ret) < 20:
        print(f"  WARNING: only {len(n500_ret)} Nifty500 obs — beta unreliable")

    bench_start = n500_ret.index.min().date()
    bench_end = n500_ret.index.max().date()
    n_obs = len(n500_ret)
    market_12m_ret = float((1 + n500_ret).prod() - 1)

    print(f"  Benchmark window : {bench_start} -> {bench_end}  ({n_obs} days)")
    print(f"  Market 12m ret   : {market_12m_ret:.2%}")

    # ── Load stock prices ──────────────────────────────────────────────────────
    symbols = list(top25_symbols)
    wide = _load_stock_prices(symbols)
    wide = wide[wide.index <= as_of_date].tail(BETA_WINDOW)
    stock_ret = wide.pct_change(fill_method=None).dropna(how="all")

    # ── Per stock: beta, cov, var, 12m return, Jensen alpha ───────────────────
    stock_rows = []
    missing = []

    for sym in sorted(symbols):
        if sym not in stock_ret.columns:
            missing.append(sym)
            stock_rows.append(
                {
                    "symbol": sym,
                    "beta_12m": np.nan,
                    "r2": np.nan,
                    "cov": np.nan,
                    "bench_var": np.nan,
                    "stock_12m_ret": np.nan,
                    "market_12m_ret": market_12m_ret,
                    "alpha_12m": np.nan,
                    "n_obs": 0,
                }
            )
            continue

        s = stock_ret[sym].dropna()
        aln = pd.concat([s, n500_ret], axis=1).dropna()
        aln.columns = ["stock", "bench"]

        if len(aln) < 20:
            beta, cov, bench_var = np.nan, np.nan, np.nan
            r2 = np.nan
            s12m = np.nan
            alpha = np.nan
        else:
            cov = aln["stock"].cov(aln["bench"])
            bench_var = aln["bench"].var()
            beta = cov / bench_var if bench_var > 0 else np.nan
            corr = aln["stock"].corr(aln["bench"])
            r2 = corr**2
            s12m = float((1 + aln["stock"]).prod() - 1)
            # Jensen alpha = stock_ret - Rf - beta * (market_ret - Rf)
            alpha = s12m - RF_ANNUAL - beta * (market_12m_ret - RF_ANNUAL)

        stock_rows.append(
            {
                "symbol": sym,
                "beta_12m": round(beta, 4) if not np.isnan(beta) else np.nan,
                "r2": round(r2, 4) if not np.isnan(r2) else np.nan,
                "cov": round(cov, 8) if not np.isnan(cov) else np.nan,
                "bench_var": round(bench_var, 8) if not np.isnan(bench_var) else np.nan,
                "stock_12m_ret": round(s12m, 4) if not np.isnan(s12m) else np.nan,
                "market_12m_ret": round(market_12m_ret, 4),
                "alpha_12m": round(alpha, 4) if not np.isnan(alpha) else np.nan,
                "n_obs": len(aln),
            }
        )

    if missing:
        print(f"  WARNING: no price data for {missing}")

    # ── Portfolio-level beta and return ────────────────────────────────────────
    # Use portfolio_symbols subset if provided (monitor mode excludes SELLs)
    port_universe = list(portfolio_symbols) if portfolio_symbols is not None else symbols
    available = [s for s in port_universe if s in stock_ret.columns]
    port_ret = stock_ret[available].mean(axis=1)
    aln_p = pd.concat([port_ret, n500_ret], axis=1).dropna()
    aln_p.columns = ["port", "bench"]

    if len(aln_p) >= 20:
        p_cov = aln_p["port"].cov(aln_p["bench"])
        p_var = aln_p["bench"].var()
        port_beta = round(p_cov / p_var, 4) if p_var > 0 else np.nan
        port_12m = round(float((1 + aln_p["port"]).prod() - 1), 4)
        port_r2 = round(aln_p["port"].corr(aln_p["bench"]) ** 2, 4)
    else:
        port_beta = np.nan
        port_12m = np.nan
        port_r2 = np.nan

    # ── Print summary ──────────────────────────────────────────────────────────
    print(f"\n  {'Symbol':<15} {'Beta':>7} {'R2':>6} {'Stock 12m':>10} {'Mkt 12m':>9} {'Alpha':>10} {'n_obs':>6}")
    print(f"  {'-' * 67}")
    for r in stock_rows:
        b = f"{r['beta_12m']:.3f}" if pd.notna(r["beta_12m"]) else "N/A"
        r2s = f"{r['r2']:.3f}" if pd.notna(r["r2"]) else "N/A"
        s12 = f"{r['stock_12m_ret']:.2%}" if pd.notna(r["stock_12m_ret"]) else "N/A"
        m12 = f"{r['market_12m_ret']:.2%}"
        alp = f"{r['alpha_12m']:.2%}" if pd.notna(r["alpha_12m"]) else "N/A"
        print(f"  {r['symbol']:<15} {b:>7} {r2s:>6} {s12:>10} {m12:>9} {alp:>10} {r['n_obs']:>6}")
    print(f"  {'PORTFOLIO':<15} {port_beta:>7.3f} {port_r2:>6.3f} {port_12m:>10.2%} {market_12m_ret:>9.2%}")

    return {
        "stocks": stock_rows,
        "portfolio_beta": port_beta,
        "portfolio_r2": port_r2,
        "portfolio_12m_ret": port_12m,
        "market_12m_ret": round(market_12m_ret, 4),
        "bench_start": bench_start,
        "bench_end": bench_end,
        "n_obs": n_obs,
    }


def beta_to_df(beta_result: dict, as_of_date: pd.Timestamp) -> pd.DataFrame:
    """
    Convert beta_result to a DataFrame.
    One row per stock + one PORTFOLIO summary row.
    Saves as parquet to signals/stage6/beta/.
    """
    rows = []
    for r in beta_result["stocks"]:
        rows.append(
            {
                "as_of_date": as_of_date.date(),
                "symbol": r["symbol"],
                "level": "stock",
                "beta_12m": r["beta_12m"],
                "r2": r["r2"],
                "cov": r["cov"],
                "bench_var": r["bench_var"],
                "stock_12m_ret": r["stock_12m_ret"],
                "market_12m_ret": r["market_12m_ret"],
                "alpha_12m": r["alpha_12m"],
                "portfolio_beta": np.nan,
                "port_12m_ret": np.nan,
                "bench_start": beta_result["bench_start"],
                "bench_end": beta_result["bench_end"],
                "n_obs": r["n_obs"],
            }
        )
    rows.append(
        {
            "as_of_date": as_of_date.date(),
            "symbol": "PORTFOLIO",
            "level": "portfolio",
            "beta_12m": np.nan,
            "cov": np.nan,
            "bench_var": np.nan,
            "stock_12m_ret": np.nan,
            "market_12m_ret": beta_result["market_12m_ret"],
            "alpha_12m": np.nan,
            "portfolio_beta": beta_result["portfolio_beta"],
            "portfolio_r2": beta_result["portfolio_r2"],
            "port_12m_ret": beta_result["portfolio_12m_ret"],
            "bench_start": beta_result["bench_start"],
            "bench_end": beta_result["bench_end"],
            "n_obs": beta_result["n_obs"],
        }
    )

    df = pd.DataFrame(rows)

    # Save parquet
    out_dir = Path("/home/ec2-user/nse-factor-engine/signals/stage6/beta")
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = as_of_date.strftime("%d%m%Y")
    out_path = out_dir / f"beta_{date_str}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"\n  Beta parquet saved: {out_path}")

    return df


def beta_for_assembly(beta_result: dict) -> dict:
    """
    Returns a lightweight dict for stage6_assemble.py to attach
    to the output CSV — only the fields needed for live monitoring.

    Keys:
        stock_beta   : dict {symbol: beta_12m}
        stock_return : dict {symbol: stock_12m_ret}
        stock_alpha  : dict {symbol: alpha_12m}
        market_return: float
        portfolio_beta: float
    """
    return {
        "stock_beta": {r["symbol"]: r["beta_12m"] for r in beta_result["stocks"]},
        "stock_return": {r["symbol"]: r["stock_12m_ret"] for r in beta_result["stocks"]},
        "stock_alpha": {r["symbol"]: r["alpha_12m"] for r in beta_result["stocks"]},
        "market_return": beta_result["market_12m_ret"],
        "portfolio_beta": beta_result["portfolio_beta"],
    }
