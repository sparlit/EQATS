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
Quality Buy & Hold Portfolio - Not Turtle-based
Buy quality-filtered stocks, hold until fundamentals deteriorate
Re-screen quarterly (or whenever run) - exit only on quality breakdown
"""

import pandas as pd

# ---------------- CONFIG ----------------
TOTAL_CAPITAL = 500000
MAX_POSITIONS = 15  # diversify across top N quality names
EXIT_ROE_THRESHOLD = 10.0  # exit if ROE falls below this
EXIT_DE_THRESHOLD = 1.0  # exit if Debt/Equity rises above this
EXIT_PROMOTER_DROP = 5.0  # exit if promoter holding drops by this many % points from entry

PORTFOLIO_FILE = "portfolio_holdings.csv"  # persists positions between runs
SCREEN_FILE = "fundamental_screen_all.csv"  # output from your screener script


# ---------------- LOAD DATA ----------------
def load_current_screen():
    return pd.read_csv(SCREEN_FILE)


def load_portfolio():
    try:
        return pd.read_csv(PORTFOLIO_FILE)
    except FileNotFoundError:
        return pd.DataFrame(
            columns=["symbol", "entry_date", "entry_roe", "entry_de", "entry_promoter", "capital_allocated", "status"]
        )


def save_portfolio(df):
    df.to_csv(PORTFOLIO_FILE, index=False)


# ---------------- REVIEW EXISTING HOLDINGS ----------------
def review_holdings(portfolio_df, screen_df):
    """Check each held stock against current fundamentals - flag for exit if degraded"""
    actions = []
    for idx, pos in portfolio_df[portfolio_df["status"] == "HOLD"].iterrows():
        sym = pos["symbol"]
        current = screen_df[screen_df["symbol"] == sym]
        if current.empty:
            actions.append((sym, "REVIEW", "No current data - check manually"))
            continue
        current = current.iloc[0]

        reasons = []
        if pd.notna(current.get("roe")) and current["roe"] < EXIT_ROE_THRESHOLD:
            reasons.append(f"ROE dropped to {current['roe']}% (below {EXIT_ROE_THRESHOLD}%)")
        if pd.notna(current.get("debt_equity")) and current["debt_equity"] > EXIT_DE_THRESHOLD:
            reasons.append(f"Debt/Equity rose to {current['debt_equity']} (above {EXIT_DE_THRESHOLD})")
        if pd.notna(current.get("promoter_holding")) and pd.notna(pos.get("entry_promoter")):
            drop = pos["entry_promoter"] - current["promoter_holding"]
            if drop > EXIT_PROMOTER_DROP:
                reasons.append(
                    f"Promoter holding dropped {drop:.1f} pts (entry {pos['entry_promoter']}% -> now {current['promoter_holding']}%)"
                )

        if reasons:
            actions.append((sym, "EXIT SIGNAL", "; ".join(reasons)))
            portfolio_df.loc[idx, "status"] = "EXIT_FLAGGED"
        else:
            actions.append((sym, "HOLD", "Fundamentals still healthy"))

    return actions, portfolio_df


# ---------------- SUGGEST NEW ENTRIES ----------------
def suggest_new_entries(portfolio_df, screen_df, max_positions):
    held_symbols = set(portfolio_df[portfolio_df["status"] == "HOLD"]["symbol"])
    open_slots = max_positions - len(held_symbols)
    if open_slots <= 0:
        return pd.DataFrame()

    quality_df = screen_df[screen_df["quality_pass"]].copy()
    quality_df = quality_df[~quality_df["symbol"].isin(held_symbols)]
    quality_df = quality_df.sort_values("roe", ascending=False)
    return quality_df.head(open_slots)


# ---------------- MAIN ----------------
def run_review():
    screen_df = load_current_screen()
    portfolio_df = load_portfolio()

    print("=" * 60)
    print("QUALITY BUY & HOLD - PORTFOLIO REVIEW")
    print("=" * 60)

    if portfolio_df.empty or (portfolio_df["status"] == "HOLD").sum() == 0:
        print("\nNo existing holdings. Building initial portfolio...\n")
        quality_df = screen_df[screen_df["quality_pass"]].sort_values("roe", ascending=False)
        top_picks = quality_df.head(MAX_POSITIONS)
        capital_per_stock = TOTAL_CAPITAL / len(top_picks) if len(top_picks) > 0 else 0

        new_rows = []
        for _, row in top_picks.iterrows():
            new_rows.append(
                {
                    "symbol": row["symbol"],
                    "entry_date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                    "entry_roe": row.get("roe"),
                    "entry_de": row.get("debt_equity"),
                    "entry_promoter": row.get("promoter_holding"),
                    "capital_allocated": round(capital_per_stock, 2),
                    "status": "HOLD",
                }
            )
        portfolio_df = pd.DataFrame(new_rows)
        save_portfolio(portfolio_df)

        print(f"Initial portfolio built: {len(portfolio_df)} stocks, Rs {capital_per_stock:,.0f} each\n")
        for _, row in portfolio_df.iterrows():
            print(
                f"  BUY  {row['symbol']:15s} ROE:{row['entry_roe']:>6} "
                f"D/E:{row['entry_de']:>5} Promoter:{row['entry_promoter']:>5}%"
            )
        return

    # Review existing holdings
    print("\nReviewing existing holdings against current fundamentals...\n")
    actions, portfolio_df = review_holdings(portfolio_df, screen_df)
    for sym, action, reason in actions:
        marker = "⚠️ " if action == "EXIT SIGNAL" else "✓ "
        print(f"{marker}{sym:15s} [{action:12s}] {reason}")

    save_portfolio(portfolio_df)

    # Suggest new entries if slots opened up
    new_entries = suggest_new_entries(portfolio_df, screen_df, MAX_POSITIONS)
    if not new_entries.empty:
        print(f"\n{'=' * 60}")
        print(f"SUGGESTED NEW ENTRIES ({len(new_entries)} slots available)")
        print(f"{'=' * 60}")
        for _, row in new_entries.iterrows():
            print(
                f"  BUY  {row['symbol']:15s} ROE:{row.get('roe', '-'):>6} "
                f"D/E:{row.get('debt_equity', '-'):>5} Promoter:{row.get('promoter_holding', '-'):>5}%"
            )

    exit_flagged = portfolio_df[portfolio_df["status"] == "EXIT_FLAGGED"]
    if not exit_flagged.empty:
        print(f"\n{'=' * 60}")
        print("ACTION NEEDED: Review and consider exiting these positions")
        print(f"{'=' * 60}")
        print(exit_flagged[["symbol", "entry_date"]].to_string(index=False))

    print(f"\nPortfolio saved to {PORTFOLIO_FILE}")


if __name__ == "__main__":
    run_review()
