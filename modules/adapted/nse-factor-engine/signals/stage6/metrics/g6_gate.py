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
Stage 6 (production) — Gate: G6

Pre-scoring filter. Removes stocks that are too operationally risky
for portfolio consideration regardless of MR score.

Selection criteria (ALL must be True):
  1. in_universe == True
  2. lower_circuit_hits_63d < 3

Note: weinstein_stage2 is NOT applied here — it is applied during
reconstitution (hybrid logic in mr_reconstitute.py).

Returns:
  passing_df  — filtered dataframe (passing stocks only)
  reject_df   — dataframe of rejected stocks with rejection_reason column
                (written to CSV by stage6_assemble.py alongside Weinstein rejects)
"""

import pandas as pd


def apply_g6_gate(signals_df: pd.DataFrame) -> tuple:

    df = signals_df[signals_df["in_universe"]].copy()

    cond_circuit = df["lower_circuit_hits_63d"] < 3
    passes_all = cond_circuit

    # ── Build reject DataFrame ──
    rejects = df[~passes_all].copy()

    if len(rejects) > 0:

        def get_failed_conditions(row):
            reasons = []
            if not (row["lower_circuit_hits_63d"] < 3):
                reasons.append(f"lower_circuit_hits_63d={int(row['lower_circuit_hits_63d'])} (>= 3)")
            return " | ".join(reasons)

        rejects["rejection_reason"] = rejects.apply(get_failed_conditions, axis=1)
        rejects["rejection_stage"] = "G6_GATE"

        reject_df = (
            rejects[["symbol", "lower_circuit_hits_63d", "rejection_stage", "rejection_reason"]]
            .copy()
            .sort_values("symbol")
            .reset_index(drop=True)
        )

        print(f"G6 gate rejects    : {len(rejects)} stocks")
    else:
        reject_df = pd.DataFrame(columns=["symbol", "lower_circuit_hits_63d", "rejection_stage", "rejection_reason"])
        print("G6 gate rejects    : 0 stocks failed")

    # ── Return passing rows ──
    passing_symbols = set(df[passes_all]["symbol"])
    passing_df = signals_df[signals_df["symbol"].isin(passing_symbols)].copy()

    return passing_df, reject_df
