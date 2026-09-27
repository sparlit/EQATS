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


"""Surveillance Pattern Analysis — Analyze returns by surveillance phase and generate signals.

Runs after daily surveillance scrape. Analyzes:
1. Returns by framework and stage
2. Recovery patterns (stocks recovering while under surveillance)
3. Price stability patterns
4. Generates actionable signals with fundamental overlay

Usage:
    python scripts/analyze_surveillance.py [--signal-date YYYY-MM-DD] [--top N]
"""


import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import sqlalchemy as sa
import yfinance as yf
from indian_quant.config.connections import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def load_surveillance_stocks(engine) -> list[dict]:
    """Load current active surveillance stocks."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
            SELECT symbol, framework, stage, stage_raw, first_seen_date, has_ibc
            FROM surveillance_stocks WHERE status = 'ACTIVE'
            ORDER BY framework, symbol
        """)
        ).fetchall()
        return [
            {
                "symbol": r[0],
                "framework": r[1],
                "stage": r[2],
                "stage_raw": r[3],
                "first_seen": str(r[4]),
                "has_ibc": r[5],
            }
            for r in rows
        ]


def load_fundamentals(engine) -> dict:
    """Load fundamentals for surveillance stocks."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
            SELECT symbol, sector, roe, pe_trailing, price_to_book, market_cap_cr,
                   deliv_pct, fundamental_score, conviction_score, close
            FROM cached_signals
            WHERE symbol IN (SELECT symbol FROM surveillance_stocks WHERE status='ACTIVE')
        """)
        ).fetchall()
        return {
            r[0]: {
                "sector": r[1],
                "roe": r[2],
                "pe": r[3],
                "pb": r[4],
                "mcap": r[5],
                "deliv_pct": r[6],
                "fund_score": r[7],
                "conviction": r[8],
                "cached_close": r[9],
            }
            for r in rows
        }


def fetch_prices(symbols: list[str], period: str = "6mo") -> dict[str, pd.DataFrame]:
    """Fetch price data for symbols via yfinance."""
    tickers = [f"{s}.NS" for s in symbols]
    results = {}

    batch_size = 50
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        try:
            data = yf.download(batch, period=period, group_by="ticker", progress=False, threads=True)
            for t in batch:
                try:
                    df = data[t].dropna() if len(batch) > 1 else data.dropna()
                    sym = t.replace(".NS", "")
                    if len(df) > 20:
                        results[sym] = df
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"Batch download error: {e}")
    return results


def compute_metrics(df: pd.DataFrame) -> dict:
    """Compute return and volatility metrics for a stock."""
    close = df["Close"].squeeze() if "Close" in df.columns else df["close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    ret_1d = close.pct_change()
    metrics = {
        "price": float(close.iloc[-1]),
        "ret_1d": float(ret_1d.iloc[-1] * 100) if len(ret_1d) > 0 else None,
        "ret_5d": float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if len(close) > 6 else None,
        "ret_1m": float((close.iloc[-1] / close.iloc[-22] - 1) * 100) if len(close) > 22 else None,
        "ret_3m": float((close.iloc[-1] / close.iloc[-66] - 1) * 100) if len(close) > 66 else None,
        "vol_20d": float(ret_1d.tail(20).std() * (252**0.5) * 100),
        "vol_60d": float(ret_1d.tail(60).std() * (252**0.5) * 100) if len(ret_1d) > 60 else None,
        "max_drawdown_3m": None,
        "above_20sma": bool(close.iloc[-1] > close.rolling(20).mean().iloc[-1]),
        "above_50sma": bool(close.iloc[-1] > close.rolling(50).mean().iloc[-1]) if len(close) > 50 else None,
    }

    # Max drawdown
    if len(close) > 66:
        peak = close.tail(66).cummax()
        dd = ((close.tail(66) - peak) / peak).min()
        metrics["max_drawdown_3m"] = float(dd * 100)

    return metrics


def classify_signal(metrics: dict, surv: dict, fund: dict) -> dict | None:
    """Classify whether a stock is a buy/sell/hold candidate."""
    signal_type = None
    strength = 0
    notes = []

    fw = surv["framework"]
    surv["stage"]

    # Safe accessors — treat None as 0
    def g(d, k, default=0):
        v = d.get(k)
        return v if v is not None else default

    # === STASM: Short-term abnormal ===
    if fw == "STASM":
        if g(metrics, "ret_1m") > 15 and g(fund, "fund_score") > 0.2:
            signal_type = "surveillance_momentum"
            strength = 60 + min(g(metrics, "ret_1m") / 5, 20)
            notes.append(f"STASM momentum: +{g(metrics, 'ret_1m'):.0f}% 1M")
        elif g(metrics, "ret_1m") < -15 and g(metrics, "vol_20d") > 50:
            signal_type = "surveillance_oversold"
            strength = 50 + min(abs(g(metrics, "ret_1m")) / 3, 20)
            notes.append(f"STASM oversold: {g(metrics, 'ret_1m'):.0f}% 1M, vol={g(metrics, 'vol_20d'):.0f}%")

    # === LTASM: Long-term abnormal ===
    elif fw == "LTASM":
        if g(metrics, "ret_3m") > 15 and g(metrics, "ret_1m") > 0:
            signal_type = "surveillance_recovery"
            strength = 55 + min(g(metrics, "ret_3m") / 5, 25)
            notes.append(f"LTASM recovery: +{g(metrics, 'ret_3m'):.0f}% 3M")
        elif g(metrics, "vol_20d", 100) < 35 and g(metrics, "ret_1m") > -5:
            signal_type = "surveillance_stable"
            strength = 45 + (35 - g(metrics, "vol_20d", 35))
            notes.append(f"LTASM stable: vol={g(metrics, 'vol_20d'):.0f}%, holding up")

    # === GSM: Fundamentally weak ===
    elif fw == "GSM":
        if g(fund, "fund_score") > 0.3 and g(metrics, "ret_1m") > 0:
            signal_type = "surveillance_fundamental_recovery"
            strength = 50 + g(fund, "fund_score") * 30
            notes.append(f"GSM with improving fundamentals: score={g(fund, 'fund_score'):.2f}")
        elif surv["has_ibc"]:
            signal_type = "avoid"
            strength = 0
            notes.append("GSM + IBC: delisting risk")

    if signal_type and signal_type != "avoid" and strength > 40:
        return {
            "signal_type": signal_type,
            "strength": round(min(100, strength), 1),
            "notes": " | ".join(notes),
        }
    return None


def main():
    parser = argparse.ArgumentParser(description="Analyze surveillance patterns")
    parser.add_argument("--signal-date", help="Date for signals")
    parser.add_argument("--top", type=int, default=10, help="Top N signals")
    args = parser.parse_args()

    engine = get_engine()

    # Load data
    log.info("Loading surveillance stocks...")
    stocks = load_surveillance_stocks(engine)
    log.info(f"  {len(stocks)} active stocks")

    log.info("Loading fundamentals...")
    fundies = load_fundamentals(engine)
    log.info(f"  {len(fundies)} with fundamentals")

    # Fetch prices
    symbols = [s["symbol"] for s in stocks]
    log.info(f"Fetching prices for {len(symbols)} stocks...")
    prices = fetch_prices(symbols)
    log.info(f"  Got prices for {len(prices)} stocks")

    # Build analysis
    surv_map = {s["symbol"]: s for s in stocks}
    results = []

    for sym, df in prices.items():
        metrics = compute_metrics(df)
        surv = surv_map.get(sym, {})
        fund = fundies.get(sym, {})

        # Compute composite score
        signal = classify_signal(metrics, surv, fund)

        results.append(
            {
                "symbol": sym,
                "framework": surv.get("framework", ""),
                "stage": surv.get("stage", ""),
                "stage_raw": surv.get("stage_raw", ""),
                "has_ibc": surv.get("has_ibc", False),
                "first_seen": surv.get("first_seen", ""),
                "sector": fund.get("sector", ""),
                "fund_score": fund.get("fund_score"),
                "conviction": fund.get("conviction"),
                **metrics,
                "signal_type": signal["signal_type"] if signal else None,
                "signal_strength": signal["strength"] if signal else None,
                "signal_notes": signal["notes"] if signal else None,
            }
        )

    df = pd.DataFrame(results)

    # === SUMMARY STATS ===
    print("\n" + "=" * 70)
    print("SURVEILLANCE PATTERN ANALYSIS")
    print("=" * 70)

    print(f"\nTotal stocks analyzed: {len(df)}")
    print(f"Stocks with signals: {len(df[df['signal_type'].notna()])}")

    # Framework breakdown
    print("\n--- FRAMEWORK PERFORMANCE ---")
    print(f"{'Framework':<10} {'Count':<7} {'1M med':<9} {'3M med':<9} {'Vol med':<9} {'Signals':<8}")
    print("-" * 52)
    for fw in ["GSM", "LTASM", "STASM"]:
        sub = df[df["framework"] == fw]
        sigs = sub[sub["signal_type"].notna()]
        print(
            f"{fw:<10} {len(sub):<7} "
            f"{sub['ret_1m'].median():+.1f}%{'':<3} "
            f"{sub['ret_3m'].median():+.1f}%{'':<3} "
            f"{sub['vol_20d'].median():.0f}%{'':<4} "
            f"{len(sigs):<8}"
        )

    # Top signals
    print("\n--- TOP SIGNALS ---")
    signals = df[df["signal_type"].notna()].sort_values("signal_strength", ascending=False)
    print(
        f"{'Symbol':<15} {'Type':<30} {'Str':<6} {'FW':<8} {'Stg':<4} {'Price':<10} {'1M%':<8} {'3M%':<8} {'Vol%':<8}"
    )
    print("-" * 95)
    for _, r in signals.head(args.top).iterrows():
        print(
            f"{r['symbol']:<15} {r['signal_type']!s:<30} {r['signal_strength']:<6.0f} "
            f"{r['framework']:<8} {r['stage']!s:<4} ₹{r['price']:<9.1f} "
            f"{r['ret_1m']:+.1f}%{'':<3} {r['ret_3m']:+.1f}%{'':<3} {r['vol_20d']:.0f}%"
        )

    # Recovery candidates
    print("\n--- RECOVERY CANDIDATES (strong 3M while under surveillance) ---")
    recovery = df[(df["ret_3m"] > 20) & (df["vol_20d"] < 60)].sort_values("ret_3m", ascending=False)
    for _, r in recovery.head(10).iterrows():
        print(
            f"  {r['symbol']:<15} {r['framework']:<8} ₹{r['price']:<8.1f} "
            f"3M: {r['ret_3m']:+.1f}%  Vol: {r['vol_20d']:.0f}%  {r['sector'] or ''}"
        )

    # Avoid list
    print("\n--- AVOID (GSM+IBC or extreme weakness) ---")
    avoid = df[(df["has_ibc"]) | ((df["ret_3m"] < -30) & (df["framework"] == "GSM"))]
    for _, r in avoid.head(10).iterrows():
        print(
            f"  {r['symbol']:<15} {r['framework']:<8} ₹{r['price']:<8.1f} 3M: {r['ret_3m']:+.1f}%  IBC: {r['has_ibc']}"
        )

    # Save full results
    df.to_csv("/tmp/surveillance_signals.csv", index=False)
    signals_only = signals.to_dict("records")
    with open("/tmp/surveillance_signals.json", "w") as f:
        json.dump(signals_only, f, indent=2, default=str)

    # Write signals to PostgreSQL surveillance_signals table
    if not signals.empty:
        signal_date = args.signal_date or pd.Timestamp.now().strftime("%Y-%m-%d")
        written = 0
        with engine.begin() as conn:
            for _, r in signals.iterrows():
                try:
                    conn.execute(
                        sa.text("""
                        INSERT INTO surveillance_signals
                            (symbol, signal_type, strength, framework, stage, price,
                             ret_1m, ret_3m, vol_20d, notes, signal_date)
                        VALUES (:symbol, :signal_type, :strength, :framework, :stage, :price,
                                :ret_1m, :ret_3m, :vol_20d, :notes, :signal_date)
                        ON CONFLICT (symbol, signal_date, signal_type) DO UPDATE SET
                            strength = EXCLUDED.strength,
                            notes = EXCLUDED.notes
                    """),
                        {
                            "symbol": r["symbol"],
                            "signal_type": r.get("signal_type"),
                            "strength": float(r.get("signal_strength", 0) or 0),
                            "framework": r.get("framework", ""),
                            "stage": r.get("stage", ""),
                            "price": float(r.get("price", 0) or 0),
                            "ret_1m": float(r.get("ret_1m", 0) or 0),
                            "ret_3m": float(r.get("ret_3m", 0) or 0),
                            "vol_20d": float(r.get("vol_20d", 0) or 0),
                            "notes": r.get("signal_notes", ""),
                            "signal_date": signal_date,
                        },
                    )
                    written += 1
                except Exception as e:
                    log.warning(f"Failed to write {r['symbol']}: {e}")
        log.info(f"Wrote {written} signals to PostgreSQL surveillance_signals table")

    log.info("Saved analysis to /tmp/surveillance_signals.csv and /tmp/surveillance_signals.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
