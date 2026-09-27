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


"""Entry price optimizer: find optimal entry zone for signal candidates.

Uses multiple methods:
  1. Support levels (recent swing lows)
  2. ATR-based pullback zones
  3. SMA confluence levels
  4. Fibonacci retracement from recent swing
  5. VWAP approximation

Usage:
    python scripts/entry_optimizer.py --symbol GOKUL
    python scripts/entry_optimizer.py --all-signals
"""


import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from indian_quant.config import load_settings


def find_support_levels(highs: pd.Series, lows: pd.Series, closes: pd.Series, lookback: int = 60) -> list[float]:
    """Find support levels using recent swing lows and round numbers."""
    recent_lows = lows.tail(lookback).tolist()
    closes.tail(lookback).tolist()

    # Find local minima (swing lows) - a low that's lower than neighbors
    supports = []
    for i in range(2, len(recent_lows) - 2):
        if (
            recent_lows[i] < recent_lows[i - 1]
            and recent_lows[i] < recent_lows[i - 2]
            and recent_lows[i] < recent_lows[i + 1]
            and recent_lows[i] < recent_lows[i + 2]
        ):
            level = float(recent_lows[i])
            # Only add if not too close to existing support
            if not any(abs(level - s) / s < 0.01 for s in supports):
                supports.append(level)

    # Add key moving averages as dynamic supports
    if len(closes) >= 20:
        sma20 = float(closes.tail(20).mean())
        if not any(abs(sma20 - s) / s < 0.02 for s in supports):
            supports.append(round(sma20, 2))

    if len(closes) >= 50:
        sma50 = float(closes.tail(50).mean())
        if not any(abs(sma50 - s) / s < 0.02 for s in supports):
            supports.append(round(sma50, 2))

    return sorted(supports)


def atr_entry_zones(close: float, atr: float) -> dict:
    """ATR-based entry zones: limit order below current price."""
    return {
        "aggressive": round(close - atr * 0.25, 2),
        "moderate": round(close - atr * 0.5, 2),
        "conservative": round(close - atr * 1.0, 2),
    }


def fibonacci_retracement(high: float, low: float, close: float) -> dict:
    """Fibonacci retracement levels from recent swing high to low."""
    diff = high - low
    if diff <= 0:
        return {}
    return {
        "fib_236": round(low + diff * 0.236, 2),
        "fib_382": round(low + diff * 0.382, 2),
        "fib_500": round(low + diff * 0.500, 2),
        "fib_618": round(low + diff * 0.618, 2),
    }


def analyze_entry(symbol: str, bars_dir: Path) -> dict | None:
    """Analyze entry opportunities for one symbol."""
    path = bars_dir / f"{symbol}.parquet"
    if not path.exists():
        return None

    df = pd.read_parquet(path)
    if df.empty or len(df) < 30:
        return None

    df["date"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("date").reset_index(drop=True)

    close = df["close"]
    high = df["high"]
    low = df["low"]

    latest_close = float(close.iloc[-1])
    float(high.iloc[-1])
    float(low.iloc[-1])

    # ATR(14)
    high_low = high - low
    high_close = (high - close.shift()).abs()
    low_close = (low - close.shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = float(tr.rolling(14, min_periods=14).mean().iloc[-1])

    # Support levels
    supports = find_support_levels(high, low, close)

    # ATR zones
    atr_zones = atr_entry_zones(latest_close, atr)

    # Fibonacci from recent 30-day swing
    recent_high = float(high.tail(30).max())
    recent_low = float(low.tail(30).min())
    fibs = fibonacci_retracement(recent_high, recent_low, latest_close)

    # SMA levels
    sma20 = float(close.tail(20).mean()) if len(close) >= 20 else None
    sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None

    # Volume-weighted average price (approximation over last 5 days)
    vwap_approx = (
        float((close.tail(5) * df["volume"].tail(5)).sum() / df["volume"].tail(5).sum())
        if "volume" in df.columns and df["volume"].tail(5).sum() > 0
        else None
    )

    # Determine recommended entry zone
    all_levels = sorted(
        [s for s in supports if s < latest_close] + [v for v in atr_zones.values() if v < latest_close],
        reverse=True,
    )

    recommended_entry = None
    stop_loss = None
    target = None

    if all_levels:
        recommended_entry = round(all_levels[0], 2)  # highest support below price
        stop_loss = round(recommended_entry * 0.93, 2)  # 7% below entry
        target = round(latest_close * 1.05, 2)  # modest 5% target

    # Confluence check: how many methods agree near this level?
    confluence_count = 0
    confluence_methods = []
    if recommended_entry:
        tolerance = recommended_entry * 0.02  # 2% tolerance
        check_levels = [
            *[("support", s) for s in supports],
            ("atr_moderate", atr_zones.get("moderate")),
            ("atr_conservative", atr_zones.get("conservative")),
            ("fib_382", fibs.get("fib_382")),
            ("fib_500", fibs.get("fib_500")),
            ("sma_20", sma20),
        ]
        for method_name, level in check_levels:
            if level is not None and abs(level - recommended_entry) <= tolerance:
                confluence_methods.append(f"{method_name}@{level:.2f}")
                confluence_count += 1

    return {
        "symbol": symbol,
        "current_price": latest_close,
        "recommended_entry": recommended_entry,
        "stop_loss": stop_loss,
        "target": target,
        "risk_reward_ratio": round((latest_close - recommended_entry) / max(recommended_entry - stop_loss, 0.01), 2)
        if recommended_entry and stop_loss
        else None,
        "confluence_count": confluence_count,
        "confluence_methods": confluence_methods,
        "supports_below": [round(s, 2) for s in supports if s < latest_close][:5],
        "atr": round(atr, 2),
        "atr_zones": atr_zones,
        "fibonacci": fibs,
        "sma_20": round(sma20, 2) if sma20 else None,
        "sma_50": round(sma50, 2) if sma50 else None,
        "vwap_approx": round(vwap_approx, 2) if vwap_approx else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Entry price optimizer")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols")
    parser.add_argument("--all-signals", action="store_true", help="Scan all delivery signals")
    args = parser.parse_args()

    settings = load_settings()
    bars_dir = settings.normalized_dir / "bars_1d" / "NSE"

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif args.all_signals:
        # Get today's signal candidates from daily signals logic
        dl_dir = settings.normalized_dir / "delivery" / "NSE"
        symbols = []
        for path in sorted(dl_dir.glob("*.parquet")):
            raw = pd.read_parquet(path, columns=["close", "deliv_pct", "ret_1d"])
            if raw.empty or len(raw) < 40:
                continue
            raw.iloc[-1]
            deliv_series = pd.to_numeric(raw["deliv_pct"], errors="coerce").dropna()
            _mean = deliv_series.tail(30).mean()
            _std = deliv_series.tail(30).std()
            z = float((raw["deliv_pct"].iloc[-1] - _mean) / _std) if _std > 0 else 0.0
            ret = float(raw["close"].pct_change().iloc[-1])
            if z >= 2 and ret >= 0.005:
                symbol = path.stem
                symbols.append(symbol)
    else:
        print("Specify --symbols or --all-signals")
        return 1

    print("=" * 70)
    print(" ENTRY PRICE OPTIMIZER")
    print("=" * 70)

    results = []
    for sym in sorted(symbols):
        result = analyze_entry(sym, bars_dir)
        if result is None:
            print(f"\n  {sym}: no data available")
            continue
        results.append(result)

        print(f"\n{'─' * 60}")
        print(f" 📈 {result['symbol']} · Current: ₹{result['current_price']}")
        print(f"{'─' * 60}")

        if result["recommended_entry"]:
            rr = result.get("risk_reward_ratio")
            conf = result.get("confluence_count", 0)
            methods = ", ".join(result.get("confluence_methods", []))

            print(f"  ✅ Recommended Entry : ₹{result['recommended_entry']}")
            print(f"     Stop Loss         : ₹{result['stop_loss']}")
            print(f"     Target            : ₹{result['target']}")
            if rr is not None:
                print(f"     Risk:Reward       : {rr}")
            print(f"     Confluence        : {conf} methods agree")
            if methods:
                print(f"                       ({methods})")
        else:
            print("  ⚠️ No clear entry zone identified")

        print("\n  📊 Reference Levels:")
        if result["supports_below"]:
            print(f"     Supports below   : {result['supports_below']}")
        if result["sma_20"]:
            print(f"     SMA-20           : ₹{result['sma_20']}")
        if result["sma_50"]:
            print(f"     SMA-50           : ₹{result['sma_50']}")
        if result["vwap_approx"]:
            print(f"     VWAP (5d)        : ₹{result['vwap_approx']}")
        print(f"     ATR(14)          : {result['atr']}")

    # Summary
    if results:
        print(f"\n{'=' * 70}")
        print(" SUMMARY — Ranked by Confluence")
        print(f"{'=' * 70}")
        ranked = sorted(results, key=lambda r: -(r.get("confluence_count") or 0))
        for r in ranked:
            entry = f"₹{r['recommended_entry']}" if r.get("recommended_entry") else "N/A"
            conf = r.get("confluence_count", 0)
            rr = r.get("risk_reward_ratio") or "-"
            print(f"  {r['symbol']:<14} entry={entry:>10} conf={conf} R:R={rr}")

    out_path = Path("docs/research/generated/entry_analysis.json")
    out_path.write_text(json.dumps(results, indent=1))
    print(f"\nsaved -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
