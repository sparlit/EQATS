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


"""Daily signal report: today's delivery-signal candidates across the universe.

Scans the latest delivery lake day, fires dz_hi_up / avoidance (dz_hi_dn)
signals for ALL stocks (no price/turnover filters), classifies by market cap
(Large/Mid/Small/Micro), sizes positions against configured risk capital,
and prints a morning sheet.

Usage:
    python scripts/daily_signals.py [--capital 25000] [--risk-pct 1] [--top 10]
"""


import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from indian_quant.config import load_settings
from indian_quant.features.delivery import add_features, prepare_frame
from indian_quant.features.market_cap import (
    get_market_cap,
    load_mcap_cache,
    save_mcap_cache,
)


def scan_symbol(path: Path) -> dict | None:
    try:
        raw = pd.read_parquet(path)
    except Exception:
        return None
    if raw.empty:
        return None
    frame = prepare_frame(raw, min_rows=min(20, len(raw)))
    if frame is None or frame.empty or "volume" not in frame.columns:
        return None
    frame = add_features(frame)
    if frame.empty:
        return None
    last = frame.iloc[-1]
    prev = frame.iloc[-2] if len(frame) > 1 else last

    notional = float(last["close"] * last["volume"])
    return {
        "symbol": str(last["symbol"]),
        "segment": str(last["segment"]),
        "close": round(float(last["close"]), 2),
        "ret_1d_pct": round(float(last["ret_1d"]) * 100, 2) if pd.notna(last["ret_1d"]) else None,
        "deliv_pct": round(float(last["deliv_pct"]), 1) if pd.notna(last["deliv_pct"]) else None,
        "deliv_z": round(float(last["deliv_z"]), 2) if pd.notna(last["deliv_z"]) else None,
        "vol_z": round(float(last["vol_z"]), 2) if pd.notna(last.get("vol_z")) else None,
        "median_turnover": round(notional, 0),
        "_dz_prev": None if pd.isna(prev.get("deliv_z")) else float(prev["deliv_z"]),
        "_ret_prev": None if pd.isna(prev.get("ret_1d")) else float(prev["ret_1d"]),
        "_date": str(last["date"].date()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily delivery-signal report")
    parser.add_argument("--capital", type=float, default=25_000.0)
    parser.add_argument(
        "--risk-pct", type=float, default=1.0, help="max account risk per position, percent"
    )
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    settings = load_settings(None if len(sys.argv) < 2 else None)
    dl_dir = settings.normalized_dir / "delivery" / "NSE"

    rows: list[dict] = []
    latest_date = ""
    for path in sorted(dl_dir.glob("*.parquet")):
        info = scan_symbol(path)
        if info is None:
            continue
        latest_date = max(latest_date, info["_date"])
        rows.append(info)

    df = pd.DataFrame(rows)
    df = df[df["_date"] == latest_date]

    # NO price/turnover filters — scan ALL stocks
    buys = df[(df["deliv_z"] >= 2) & (df["ret_1d_pct"] >= 0.5)].sort_values(
        "deliv_z", ascending=False
    )

    avoid = df[(df["deliv_z"] >= 2) & (df["ret_1d_pct"] <= -0.5)].sort_values(
        "deliv_z", ascending=False
    )

    # Classify by market cap
    from indian_quant.ingestion.router import SourceRouter

    router = SourceRouter()
    cache = load_mcap_cache()

    mcap_data = {}
    for sym in set(buys["symbol"].tolist() + avoid["symbol"].tolist()):
        info = get_market_cap(router, sym, "NSE", cache)
        mcap_data[sym] = info

    for df_part in [buys, avoid]:
        if df_part.empty:
            continue
        df_part["market_cap_cr"] = df_part["symbol"].map(
            lambda s: mcap_data.get(s, {}).get("market_cap_cr", 0)
        )
        df_part["market_cap_class"] = df_part["symbol"].map(
            lambda s: mcap_data.get(s, {}).get("market_cap_class", "Other")
        )

    save_mcap_cache(cache)

    risk_rupees = args.capital * args.risk_pct / 100.0

    def size(row) -> int:
        stop_dist = row["close"] * 0.07
        if stop_dist <= 0:
            return 0
        by_risk = int(risk_rupees // stop_dist)
        by_capital = int((args.capital * 0.3) // (row["close"] * 1))
        return max(0, min(by_risk, by_capital))

    print("=" * 90)
    print(f" DAILY DELIVERY SIGNALS · data through {latest_date} · ALL stocks (no price filter)")
    print(f" capital ₹{args.capital:,.0f} | risk/pos {args.risk_pct}% = ₹{risk_rupees:,.0f}")
    print("=" * 90)

    if buys.empty:
        print("\n(no BUY candidates today - discipline is also a position)")
    else:
        # Group by market cap
        for tier in ["Large Cap", "Mid Cap", "Small Cap", "Micro Cap"]:
            tier_buys = buys[buys["market_cap_class"] == tier]
            if tier_buys.empty:
                continue
            print(f"\n🟢 {tier.upper()} — ACCUMULATION CANDIDATES ({len(tier_buys)} stocks)\n")
            for _, r in tier_buys.head(args.top).iterrows():
                qty = size(r)
                mcap_str = f"₹{r['market_cap_cr']:,.0f}Cr" if r.get("market_cap_cr") else "—"
                print(
                    f"  {r['symbol']:<14} {r['segment']:<4} ₹{r['close']:>9,.2f} "
                    f"| deliv {r['deliv_pct']}% (z {r['deliv_z']}) "
                    f"| vol z {r['vol_z']} | mcap {mcap_str} | qty {qty}"
                )

    if not avoid.empty:
        print(f"\n🔴 AVOID / EXIT-WATCH ({len(avoid)} stocks)\n")
        for _, r in avoid.head(args.top).iterrows():
            mcap_str = f"₹{r['market_cap_cr']:,.0f}Cr" if r.get("market_cap_cr") else "—"
            print(
                f"  {r['symbol']:<14} {r['segment']:<4} ₹{r['close']:>9,.2f} "
                f"| deliv {r['deliv_pct']}% (z {r['deliv_z']}) | mcap {mcap_str}"
            )

    # Summary
    print(f"\n{'=' * 90}")
    print(f" Total: {len(buys)} BUY candidates, {len(avoid)} AVOID across {len(df)} stocks scanned")
    print(" Market cap breakdown BUY: ", end="")
    for tier in ["Large Cap", "Mid Cap", "Small Cap", "Micro Cap"]:
        n = len(buys[buys["market_cap_class"] == tier])
        if n > 0:
            print(f"{tier}={n} ", end="")
    print()

    print("\nNotes: signals are research output, not advice. Entry via limit orders.")
    print("Re-run after 18:30 IST for same-day delivery data refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
