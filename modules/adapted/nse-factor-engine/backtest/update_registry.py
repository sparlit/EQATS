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
Backtest Registry Updater

Reads all summary CSVs and activity CSVs from backtest/results/ and
maintains a single registry.csv with one row per variant per run.
Deduplicates on (run_date, Variant) — reruns don't create duplicates.

Usage:
  python3 backtest/update_registry.py

Registry columns:
  run_date, script, Variant, Description,
  CAGR, BM CAGR, Alpha, Sharpe, Calmar, Max DD,
  Pct_Positive_Periods, Avg Turnover, Avg Universe, NAV end (M), Periods,
  Ulcer_Index, Martin_Ratio,
  Total_Positions, Winners, Losers, Win_Rate_Pct,
  Avg_Pos_Return_Pct, Avg_Neg_Return_Pct,
  Expectancy_Ratio, Profit_Factor, K_Ratio,
  Avg_Hold_Days, Max_Hold_Days, Max_Hold_Symbol
"""

import glob
import os
import re

import numpy as np
import pandas as pd

RESULTS_DIR = "/home/ec2-user/nse-factor-engine/backtest/results"
REGISTRY = f"{RESULTS_DIR}/registry.csv"

SCRIPT_MAP = {
    "hybrid_summary": "simulation_fri_signal_mon_open_backtest_mr_hybrid.py",
    "12way_summary": "simulation_fri_signal_mon_open_backtest_mr_12way.py",
    "variants_summary": "simulation_fri_signal_mon_open_backtest_mr_variants.py",
    "targeted_summary": "simulation_fri_signal_mon_open_backtest_mr_targeted.py",
}

REGISTRY_COLS = [
    "run_date",
    "script",
    "Variant",
    "Description",
    "CAGR",
    "BM CAGR",
    "Alpha",
    "Sharpe",
    "Calmar",
    "Max DD",
    "Pct_Positive_Periods",
    "Avg Turnover",
    "NAV end (M)",
    "Periods",
    "Ulcer_Index",
    "Martin_Ratio",
    "Total_Positions",
    "Winners",
    "Losers",
    "Win_Rate_Pct",
    "Avg_Pos_Return_Pct",
    "Avg_Neg_Return_Pct",
    "Expectancy_Ratio",
    "Profit_Factor",
    "K_Ratio",
    "Avg_Hold_Days",
    "Max_Hold_Days",
    "Max_Hold_Symbol",
]


# ── Ulcer Index ────────────────────────────────────────────────────────────────
def ulcer_index(nav_series):
    nav = pd.Series(nav_series).values
    running_max = np.maximum.accumulate(nav)
    dd_pct = (nav - running_max) / running_max * 100
    return np.sqrt(np.mean(dd_pct**2))


def martin_ratio(nav_series, weekly_rets, rf_annual=0.07):
    ui = ulcer_index(nav_series)
    if ui == 0:
        return np.nan
    rets = pd.Series(weekly_rets).iloc[1:].dropna()
    cum = (1 + rets).prod() - 1
    ny = len(rets) / 52
    cagr = (1 + cum) ** (1 / ny) - 1 if ny > 0 else np.nan
    return (cagr - rf_annual) / (ui / 100)


# ── Activity metrics ───────────────────────────────────────────────────────────
def activity_metrics(fpath):
    df = pd.read_csv(fpath)
    df["friday_date"] = pd.to_datetime(df["friday_date"])

    buys = df[df["action"] == "BUY"][["symbol", "friday_date", "value"]].copy()
    sells = df[df["action"] == "SELL"][["symbol", "friday_date", "value"]].copy()

    buys = buys.sort_values(["symbol", "friday_date"]).reset_index(drop=True)
    sells = sells.sort_values(["symbol", "friday_date"]).reset_index(drop=True)

    positions = []
    for sym in buys["symbol"].unique():
        sb = buys[buys["symbol"] == sym].reset_index(drop=True)
        ss = sells[sells["symbol"] == sym].reset_index(drop=True)
        for i in range(min(len(sb), len(ss))):
            buy_val = sb.loc[i, "value"]
            sell_val = ss.loc[i, "value"]
            pnl = sell_val - buy_val
            ret = pnl / buy_val if buy_val != 0 else np.nan
            hold = (ss.loc[i, "friday_date"] - sb.loc[i, "friday_date"]).days
            positions.append(
                {
                    "symbol": sym,
                    "sell_date": ss.loc[i, "friday_date"],
                    "pnl": pnl,
                    "ret": ret,
                    "hold": hold,
                }
            )

    if not positions:
        return {}

    pos_df = pd.DataFrame(positions)
    winners = pos_df[pos_df["pnl"] > 0]
    losers = pos_df[pos_df["pnl"] <= 0]
    total = len(pos_df)
    win_rate = len(winners) / total
    loss_rate = len(losers) / total

    avg_win = winners["ret"].mean() if len(winners) > 0 else 0
    avg_loss = abs(losers["ret"].mean()) if len(losers) > 0 else 0

    expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
    gross_profit = winners["pnl"].sum()
    gross_loss = abs(losers["pnl"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.nan

    # K-Ratio
    pos_sorted = pos_df.sort_values("sell_date").reset_index(drop=True)
    clr = np.log1p(pos_sorted["ret"].fillna(0)).cumsum().values
    x = np.arange(len(clr))
    if len(x) > 2:
        coeffs = np.polyfit(x, clr, 1)
        residuals = clr - np.polyval(coeffs, x)
        se = np.std(residuals, ddof=2) / (np.std(x, ddof=1) * np.sqrt(len(x)))
        k_ratio = coeffs[0] / se if se > 0 else np.nan
    else:
        k_ratio = np.nan

    max_idx = pos_df["hold"].idxmax()

    return {
        "Total_Positions": total,
        "Winners": len(winners),
        "Losers": len(losers),
        "Win_Rate_Pct": round(win_rate * 100, 2),
        "Avg_Pos_Return_Pct": round(avg_win * 100, 3),
        "Avg_Neg_Return_Pct": round(avg_loss * 100, 3),
        "Expectancy_Ratio": round(expectancy, 4),
        "Profit_Factor": round(profit_factor, 3),
        "K_Ratio": round(k_ratio, 3),
        "Avg_Hold_Days": round(pos_df["hold"].mean(), 1),
        "Max_Hold_Days": int(pos_df["hold"].max()),
        "Max_Hold_Symbol": pos_df.loc[max_idx, "symbol"],
    }


# ── Load existing registry ─────────────────────────────────────────────────────
if os.path.exists(REGISTRY):
    registry = pd.read_csv(REGISTRY)
    # Rename Hit Rate -> Pct_Positive_Periods if old column exists
    if "Hit Rate" in registry.columns:
        registry = registry.rename(columns={"Hit Rate": "Pct_Positive_Periods"})
    print(f"Existing registry: {len(registry)} rows")
else:
    registry = pd.DataFrame(columns=REGISTRY_COLS)
    print("No existing registry — creating fresh")


# ── Find latest weekly returns and activity files per variant ──────────────────
def latest_files_by_variant(pattern, split_key):
    files = glob.glob(f"{RESULTS_DIR}/{pattern}")
    latest = {}
    for f in files:
        base = os.path.basename(f)
        variant = base.split(split_key)[0]
        date_str = base.split(split_key)[1].replace(".csv", "")
        if variant not in latest or date_str > latest[variant][1]:
            latest[variant] = (f, date_str)
    return latest


wr_latest = latest_files_by_variant("*_weekly_returns_*.csv", "_weekly_returns_")
act_latest = latest_files_by_variant("*_activity_*.csv", "_activity_")

# Filter out backtest_ files
wr_latest = {k: v for k, v in wr_latest.items() if not k.startswith("backtest_")}
act_latest = {k: v for k, v in act_latest.items() if not k.startswith("backtest_")}

# ── Find all summary CSVs ──────────────────────────────────────────────────────
summary_files = glob.glob(f"{RESULTS_DIR}/*_summary_*.csv")
summary_files = [f for f in summary_files if "registry" not in f and "tax_gains" not in f]
summary_files.sort()
print(f"Found {len(summary_files)} summary files")

new_rows = []

for fpath in summary_files:
    fname = os.path.basename(fpath)

    date_match = re.search(r"(\d{8})\.csv$", fname)
    if not date_match:
        print(f"  Skipping — cannot parse date: {fname}")
        continue
    date_str = date_match.group(1)
    run_date = f"{date_str[0:2]}/{date_str[2:4]}/{date_str[4:8]}"

    script = "unknown"
    for key, val in SCRIPT_MAP.items():
        if fname.startswith(key):
            script = val
            break

    df = pd.read_csv(fpath)

    for _, row in df.iterrows():
        variant = row.get("Variant", "")

        # ── Ulcer + Martin from weekly returns ──
        ulcer, martin = np.nan, np.nan
        if variant in wr_latest:
            wr_df = pd.read_csv(wr_latest[variant][0])
            ulcer = round(ulcer_index(wr_df["nav"]), 3)
            martin = round(martin_ratio(wr_df["nav"], wr_df["weekly_ret"]), 3)

        # ── Activity metrics ──
        act_m = {}
        if variant in act_latest:
            act_m = activity_metrics(act_latest[variant][0])

        new_rows.append(
            {
                "run_date": run_date,
                "script": script,
                "Variant": variant,
                "Description": row.get("Description", ""),
                "CAGR": row.get("CAGR", None),
                "BM CAGR": row.get("BM CAGR", None),
                "Alpha": row.get("Alpha", None),
                "Sharpe": row.get("Sharpe", None),
                "Calmar": row.get("Calmar", None),
                "Max DD": row.get("Max DD", None),
                "Pct_Positive_Periods": row.get("Hit Rate", row.get("Pct_Positive_Periods", None)),
                "Avg Turnover": row.get("Avg Turnover", None),
                "NAV end (M)": row.get("NAV end (M)", None),
                "Periods": row.get("Periods", row.get("Weeks", None)),
                "Ulcer_Index": ulcer,
                "Martin_Ratio": martin,
                "Total_Positions": act_m.get("Total_Positions", np.nan),
                "Winners": act_m.get("Winners", np.nan),
                "Losers": act_m.get("Losers", np.nan),
                "Win_Rate_Pct": act_m.get("Win_Rate_Pct", np.nan),
                "Avg_Pos_Return_Pct": act_m.get("Avg_Pos_Return_Pct", np.nan),
                "Avg_Neg_Return_Pct": act_m.get("Avg_Neg_Return_Pct", np.nan),
                "Expectancy_Ratio": act_m.get("Expectancy_Ratio", np.nan),
                "Profit_Factor": act_m.get("Profit_Factor", np.nan),
                "K_Ratio": act_m.get("K_Ratio", np.nan),
                "Avg_Hold_Days": act_m.get("Avg_Hold_Days", np.nan),
                "Max_Hold_Days": act_m.get("Max_Hold_Days", np.nan),
                "Max_Hold_Symbol": act_m.get("Max_Hold_Symbol", ""),
            }
        )

    print(f"  Processed: {fname} — {len(df)} variants")

# ── Merge and deduplicate ──────────────────────────────────────────────────────
new_df = pd.DataFrame(new_rows, columns=REGISTRY_COLS)
combined = pd.concat([registry, new_df], ignore_index=True)
combined = combined.drop_duplicates(subset=["run_date", "Variant"], keep="last")
combined = combined.sort_values("NAV end (M)", ascending=False).reset_index(drop=True)

# ── Write registry ─────────────────────────────────────────────────────────────
# Drop legacy columns if present
for _drop_col in ["Avg Universe"]:
    if _drop_col in combined.columns:
        combined = combined.drop(columns=[_drop_col])

combined.to_csv(REGISTRY, index=False)
print(f"\nRegistry updated: {len(combined)} rows -> {REGISTRY}")

# ── Print summary ──────────────────────────────────────────────────────────────
print("\n" + "=" * 130)
print("REGISTRY — sorted by NAV descending")
print("=" * 130)
print(
    "%-13s %-12s %-30s %7s %7s %7s %7s %6s %6s %8s %8s %8s %8s"
    % (
        "run_date",
        "Variant",
        "Description",
        "CAGR",
        "Alpha",
        "Sharpe",
        "Calmar",
        "MaxDD",
        "Pct+Mo",
        "Ulcer",
        "Martin",
        "ExpRatio",
        "ProfFact",
    )
)
print("-" * 130)
for _, r in combined.iterrows():
    print(
        "%-13s %-12s %-30s %6.2f%% %6.2f%% %7.3f %7.3f %6.2f%% %5.1f%% %8.3f %8.3f %8.4f %8.3f"
        % (
            r["run_date"],
            r["Variant"],
            str(r["Description"])[:30],
            float(r["CAGR"]) * 100,
            float(r["Alpha"]) * 100,
            float(r["Sharpe"]),
            float(r["Calmar"]),
            float(r["Max DD"]) * 100,
            float(r["Pct_Positive_Periods"]) * 100,
            float(r["Ulcer_Index"]) if pd.notna(r["Ulcer_Index"]) else 0,
            float(r["Martin_Ratio"]) if pd.notna(r["Martin_Ratio"]) else 0,
            float(r["Expectancy_Ratio"]) if pd.notna(r["Expectancy_Ratio"]) else 0,
            float(r["Profit_Factor"]) if pd.notna(r["Profit_Factor"]) else 0,
        )
    )
print("=" * 130)
