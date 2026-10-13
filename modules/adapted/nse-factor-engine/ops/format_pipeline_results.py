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
format_pipeline_results.py
Reads today's portfolio_recommendations parquet (IST date),
formats 9 fields into two sections:
  1. BUY / HOLD / SELL
  2. WATCHLIST
Sections are separated by WATCHLIST_SEP so the bot can split and send as
two messages. Prints to stdout. Exits 1 with message if file not found.

Run standalone to verify output:
  python3 /home/ec2-user/nse-factor-engine/ops/format_pipeline_results.py
"""

import sys
from pathlib import Path

import pandas as pd

BASE = Path("/home/ec2-user/nse-factor-engine")
SIGNALS_DIR = BASE / "signals" / "stage6"
WATCHLIST_SEP = "<<<WATCHLIST>>>"
COLS = [
    "symbol",
    "as_of_date",
    "rsi_14",
    "market_cap_cr",
    "adtv_63_cr",
    "g6_pool_size",
    "tier",
    "action",
    "run_date",
]
ACTION_ORDER = ["BUY", "HOLD", "SELL"]
ACTION_EMOJI = {"BUY": "🟢", "HOLD": "🔵", "SELL": "🔴", "WATCHLIST": "📋"}


def fmt_row(row):
    rsi = f"{row['rsi_14']:.1f}" if pd.notna(row["rsi_14"]) else "—"
    mcap = f"{row['market_cap_cr']:.0f}cr" if pd.notna(row["market_cap_cr"]) else "—"
    adtv = f"{row['adtv_63_cr']:.0f}cr" if pd.notna(row["adtv_63_cr"]) else "—"
    pool = str(int(row["g6_pool_size"])) if pd.notna(row["g6_pool_size"]) else "—"
    return f"{row['symbol']}  RSI:{rsi} · MCap:{mcap} · ADTV:{adtv} · G6_Pool:{pool}"


def main():
    run_date_str = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%d%m%Y")
    parquet_path = SIGNALS_DIR / f"portfolio_recommendations_{run_date_str}.parquet"

    if not parquet_path.exists():
        print(
            f"ERROR: {parquet_path.name} not found. Stage 6 may not have completed successfully.",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_parquet(parquet_path)[COLS]
    run_date = pd.to_datetime(df["run_date"].iloc[0]).strftime("%d %b %Y")
    as_of = pd.to_datetime(df["as_of_date"].iloc[0]).strftime("%d %b %Y")

    # ── Section 1: BUY / HOLD / SELL ──────────────────────────────────────────
    lines = [
        "NSE Pipeline Results",
        f"Run: {run_date}  |  As of: {as_of}",
        "",
    ]
    for action in ACTION_ORDER:
        subset = df[df["action"] == action]
        if subset.empty:
            continue
        lines.append(f"{ACTION_EMOJI[action]} {action} ({len(subset)})")
        for _, row in subset.iterrows():
            lines.append(fmt_row(row))
        lines.append("")

    main_section = "\n".join(lines).strip()

    # ── Section 2: WATCHLIST ───────────────────────────────────────────────────
    watchlist = df[df["action"] == "WATCHLIST"]
    wl_lines = [f"📋 WATCHLIST ({len(watchlist)})", ""]
    for _, row in watchlist.iterrows():
        wl_lines.append(fmt_row(row))

    watchlist_section = "\n".join(wl_lines).strip()

    # ── Output ─────────────────────────────────────────────────────────────────
    print(main_section)
    print(WATCHLIST_SEP)
    print(watchlist_section)


if __name__ == "__main__":
    main()
