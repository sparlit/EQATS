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
Generate next-month stock picks for active strategies.

Reads current momentum ratios from stock_performance (already computed by
app/momentum.py after each daily sync), re-normalises z-scores within the
High Cap universe, and writes the top-15 selections to
web/src/data/strategy_picks.json.

Run this AFTER the momentum calculation step every day.  On the evening of
the last trading day of the month the file will contain the exact stocks that
each strategy will hold next month, so picks are visible before the first
trading day's market open.
"""

import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Load only DATABASE_URL from web/.env — do NOT use MIN_MARKET_CAP_CR from there.
# That env var controls the Vercel display filter (1500 Cr) which differs from
# the backtest universe threshold (2000 Cr). Picks must match the backtest exactly.
load_dotenv(os.path.join(base_dir, "web", ".env"))

sys.path.append(base_dir)
from app.database import DatabaseManager

# Must match the backtest scripts — do not read from env.
HIGH_CAP_THRESHOLD_CR = 2000


def zscore_col(series: pd.Series) -> pd.Series:
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def pick_top_n(df: pd.DataFrame, z_cols: list[str], n: int = 15) -> pd.DataFrame:
    """Re-normalise z-scores within df and return top-n rows."""
    for col in z_cols:
        df[f"z_{col}_local"] = zscore_col(df[col])
    df["weighted_z"] = df[[f"z_{col}_local" for col in z_cols]].mean(axis=1)
    return df.nlargest(n, "weighted_z").reset_index(drop=True).assign(rank=lambda d: d.index + 1)


def format_picks(df: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in df.iterrows():
        rows.append(
            {
                "rank": int(r["rank"]),
                "symbol": r["nse_symbol"],
                "name": r.get("name") or r["nse_symbol"],
                "market_cap_cr": round(r["market_cap"] / 1e7) if r["market_cap"] else None,
                "weighted_z": round(float(r["weighted_z"]), 4),
                "mr_3m": round(float(r["mr_3m"]), 4) if pd.notna(r.get("mr_3m")) else None,
                "mr_6m": round(float(r["mr_6m"]), 4) if pd.notna(r.get("mr_6m")) else None,
                "mr_1y": round(float(r["mr_1y"]), 4) if pd.notna(r.get("mr_1y")) else None,
            }
        )
    return rows


def main():
    db = DatabaseManager()
    session = db.Session()

    min_mcap_cr = HIGH_CAP_THRESHOLD_CR
    min_mcap = min_mcap_cr * 1e7

    print(f"Fetching High Cap stocks (market_cap >= {min_mcap_cr} Cr)...")

    rows = session.execute(
        text("""
        SELECT
            s.id        AS stock_id,
            s.nse_symbol,
            s.name,
            s.market_cap,
            sp.mr_3m,
            sp.mr_6m,
            sp.mr_1y,
            sp.updated_at
        FROM stocks s
        JOIN stock_performance sp ON sp.stock_id = s.id
        WHERE s.is_active = true
          AND s.market_cap >= :min_mcap
          AND sp.mr_3m IS NOT NULL
          AND sp.mr_6m IS NOT NULL
          AND sp.mr_1y IS NOT NULL
    """),
        {"min_mcap": min_mcap},
    ).fetchall()

    session.close()

    df = pd.DataFrame(
        rows, columns=["stock_id", "nse_symbol", "name", "market_cap", "mr_3m", "mr_6m", "mr_1y", "updated_at"]
    )

    print(f"  {len(df)} eligible stocks found.")

    if df.empty:
        print("No data — exiting.")
        return

    # Infer the data-as-of date from the most common updated_at value
    try:
        as_of = pd.to_datetime(df["updated_at"]).dt.date.mode()[0].isoformat()
    except Exception:
        as_of = datetime.now().date().isoformat()

    # ── Strategy 1: Momentum (3M + 6M + 1Y) ─────────────────────────────────
    # Used by: Momentum Strategy, Momentum + 10% Stop
    mom_picks = pick_top_n(df.copy(), ["mr_3m", "mr_6m", "mr_1y"])

    # ── Strategy 2: Simple Momentum (6M + 1Y only) ───────────────────────────
    # Used by: Simple Momentum (High Cap), Simple Momentum (High Cap) + 10% Stop
    simple_picks = pick_top_n(df.copy(), ["mr_6m", "mr_1y"])

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": as_of,
        "universe": f"High Cap (market_cap >= {min_mcap_cr} Cr)",
        "universe_size": len(df),
        "picks": {
            "momentum": {
                "description": "Top 15 by 3M + 6M + 1Y momentum (equal weight)",
                "used_by": [
                    "Momentum Strategy",
                    "Momentum + 10% Stop",
                ],
                "stocks": format_picks(mom_picks),
            },
            "simple_momentum_high_cap": {
                "description": "Top 15 by 6M + 1Y momentum (equal weight)",
                "used_by": [
                    "Simple Momentum (High Cap)",
                    "Simple Momentum (High Cap) + 10% Stop",
                ],
                "stocks": format_picks(simple_picks),
            },
        },
    }

    out_path = os.path.join(base_dir, "web", "src", "data", "strategy_picks.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nPicks written to {out_path}")

    # ── Monthly snapshot (frozen on first run of each month) ─────────────────
    # check_stop_losses.py reads this to monitor the stocks actually bought,
    # even if those stocks later fall out of the daily top-15.
    snapshot_path = os.path.join(base_dir, "web", "src", "data", "monthly_picks_snapshot.json")
    current_month = datetime.now().strftime("%Y-%m")

    snapshot = {}
    if os.path.exists(snapshot_path):
        with open(snapshot_path) as f:
            snapshot = json.load(f)

    if current_month not in snapshot:
        snapshot[current_month] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "as_of_date": as_of,
            "picks": output["picks"],
        }
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        print(f"  Monthly snapshot created for {current_month}")
    else:
        print(f"  Monthly snapshot for {current_month} already exists — skipped")
    print(f"  As-of date : {as_of}")
    print(f"  Universe   : {len(df)} stocks")
    print("\nMomentum (3M+6M+1Y) — Top 15:")
    for s in output["picks"]["momentum"]["stocks"]:
        print(f"  {s['rank']:>2}. {s['symbol']:<14}  z={s['weighted_z']:+.3f}")
    print("\nSimple Momentum High Cap (6M+1Y) — Top 15:")
    for s in output["picks"]["simple_momentum_high_cap"]["stocks"]:
        print(f"  {s['rank']:>2}. {s['symbol']:<14}  z={s['weighted_z']:+.3f}")


if __name__ == "__main__":
    main()
