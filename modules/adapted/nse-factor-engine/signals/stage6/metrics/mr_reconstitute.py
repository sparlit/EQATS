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
Stage 6 — MR_M Reconstitution

Execution order:

Step 3: Holdings rank > BUFFER_ZONE (38) or unscored -> forced out (SELL).

Step 4: Non-holders with rank <= FORCED_IN_N (12) -> forced in (BUY).
        Each forced-in stock unconditionally displaces the lowest momentum
        score holding currently in the portfolio.

Step 5: Remaining holdings with rank <= BUFFER_ZONE -> retained (HOLD).

Step 6: Fill remaining slots with non-holders in rank order until
        portfolio count = PORTFOLIO_N (25).

Final portfolio = exactly 25 stocks.
"""

import pandas as pd

PORTFOLIO_N = 25
FORCED_IN_N = 12
BUFFER_ZONE = 38


def apply_reconstitution(ranked_df: pd.DataFrame, current_holdings: set) -> tuple:

    df = ranked_df.copy()
    all_scored = set(df["symbol"])
    rank_lookup = dict(zip(df["symbol"], df["mr_rank"].astype(int), strict=False))
    score_lookup = dict(zip(df["symbol"], df["norm_momentum_score"], strict=False))

    # Holdings not in scored universe at all
    unscored = current_holdings - all_scored
    if unscored:
        print(f"WARNING: {len(unscored)} holdings not in scored universe (force SELL): {sorted(unscored)}")

    # ── Step 3: Remove holdings ranked > BUFFER_ZONE or unscored ──────────
    portfolio = {s for s in current_holdings if s in all_scored and rank_lookup[s] <= BUFFER_ZONE}
    forced_out = (current_holdings - portfolio) | unscored

    print(f"\nStep 3 — forced out (rank > {BUFFER_ZONE} or unscored): {len(forced_out)}  {sorted(forced_out)}")

    # ── Step 4: Non-holders rank <= FORCED_IN_N -> forced in ──────────────
    # Each displaces the lowest momentum score holding unconditionally.
    forced_in_candidates = df[(df["mr_rank"] <= FORCED_IN_N) & (~df["symbol"].isin(current_holdings))].sort_values(
        "mr_rank"
    )

    step4_forced_in = []
    step4_displaced = []
    for _, row in forced_in_candidates.iterrows():
        new_stock = row["symbol"]
        holdings_in_port = portfolio & current_holdings
        if holdings_in_port:
            weakest = min(holdings_in_port, key=lambda s: score_lookup.get(s, 0))
            portfolio.discard(weakest)
            forced_out.add(weakest)
            step4_displaced.append(weakest)
        portfolio.add(new_stock)
        step4_forced_in.append(new_stock)

    print(f"Step 4 — forced in  (non-holders rank <= {FORCED_IN_N}): {len(step4_forced_in)}  {sorted(step4_forced_in)}")
    print(f"Step 4 — displaced  (lowest scoring holdings bumped): {len(step4_displaced)}  {sorted(step4_displaced)}")

    # ── Step 5: Retained holdings ─────────────────────────────────────────
    retained = sorted(portfolio & current_holdings, key=lambda s: rank_lookup.get(s, 999))
    print(f"Step 5 — retained   (holdings rank <= {BUFFER_ZONE}, survived): {len(retained)}  {sorted(retained)}")

    # ── Step 6: Fill remaining slots with non-holders by rank ─────────────
    step6_fills = []
    slots_remaining = PORTFOLIO_N - len(portfolio)
    if slots_remaining > 0:
        fill_pool = df[~df["symbol"].isin(portfolio) & ~df["symbol"].isin(current_holdings)].sort_values("mr_rank")
        for _, row in fill_pool.iterrows():
            if slots_remaining == 0:
                break
            portfolio.add(row["symbol"])
            step6_fills.append(row["symbol"])
            slots_remaining -= 1

    print(f"Step 6 — filled     (non-holders by rank): {len(step6_fills)}  {sorted(step6_fills)}")

    top25_symbols = portfolio

    # ── Watchlist: non-holders rank <= BUFFER_ZONE not in portfolio ────────
    watchlist_pool = set(
        df[
            (df["mr_rank"] <= BUFFER_ZONE)
            & (~df["symbol"].isin(top25_symbols))
            & (~df["symbol"].isin(current_holdings))
        ]["symbol"]
    )

    # ── Assign actions and tiers ───────────────────────────────────────────
    def get_action(row):
        sym = row["symbol"]
        if sym in top25_symbols:
            return "HOLD" if sym in current_holdings else "BUY"
        if sym in current_holdings or sym in unscored:
            return "SELL"
        if sym in watchlist_pool:
            return "WATCHLIST"
        return None

    def get_tier(row):
        sym = row["symbol"]
        if sym in top25_symbols:
            return "TOP_25"
        if sym in current_holdings:
            return "SELL"
        if sym in watchlist_pool:
            return "WATCHLIST"
        return None

    df["action"] = df.apply(get_action, axis=1)
    df["tier"] = df.apply(get_tier, axis=1)

    output_df = df[df["action"].notna()].copy()

    # Add unscored holdings as SELL rows
    if unscored:
        unscored_rows = pd.DataFrame(
            {
                "symbol": sorted(unscored),
                "tier": "SELL",
                "action": "SELL",
            }
        )
        output_df = pd.concat([output_df, unscored_rows], ignore_index=True)

    print("\nReconstitution output:")
    print(f"  TOP_25    : {(output_df['tier'] == 'TOP_25').sum()}")
    print(f"    HOLD    : {(output_df['action'] == 'HOLD').sum()}")
    print(f"    BUY     : {(output_df['action'] == 'BUY').sum()}")
    print(f"  SELL      : {(output_df['action'] == 'SELL').sum()}")
    print(f"  WATCHLIST : {(output_df['action'] == 'WATCHLIST').sum()}")

    # Empty rejects DataFrame — keeps stage6_assemble.py signature intact
    weinstein_rejects = pd.DataFrame(
        columns=[
            "symbol",
            "mr_rank",
            "norm_momentum_score",
            "weighted_z",
            "ret_12m1m",
            "weinstein_stage2",
            "rejection_stage",
            "rejection_reason",
        ]
    )

    return output_df, top25_symbols, weinstein_rejects
