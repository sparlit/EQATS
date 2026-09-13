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
Daily Swing Score for the "Strong Stock + Strong Sector + High RS + High
ADR" swing/positional setup (see scripts/backtest_swing_setup.py for the
historical validation of this idea).

  strong_stock_score - Stage 2 trend template: (criteria passed / 7) * 100.
                        Only the 7 pure trend-template criteria (price vs
                        50/150/200 SMA, SMA ordering, 200-SMA rising, 52w
                        hi/lo bands) - RS is excluded here since it's
                        already its own component below. Used as a GATE,
                        not blended into the score (see below).
  rs_score           - stage2_rs_rank, as computed by calculate_stage2.py
                        (63-day return percentile across the universe).
                        Read directly, not recomputed.
  sector_score       - percentile rank of the stock's mapped sector index's
                        1-month return (index_performance.change_1m) among
                        all sector indices.
  adr_score          - percentile rank of adr_pct (from calculate_adr.py)
                        across the universe.

Strong Stock and RS turned out to be correlated ~0.66 in practice (both
are largely measuring "is this stock trending up", just from different
angles), and averaging all 4 let stocks with zero real trend structure
(strong_stock_score = 0, i.e. failing every Stage 2 criterion) still post
a decent swing_score by having high RS/Sector/ADR. So strong_stock_score
is now a GATE (>= 50, i.e. at least 4/7 criteria) rather than a blended
component - stocks that don't clear it get no swing_score at all:

  swing_score = mean(rs_score, sector_score, adr_score)  if strong_stock_score >= 50
              = None                                      otherwise

Must run AFTER calculate_stage2.py (needs stage2_rs_rank) and
calculate_adr.py (needs adr_pct) for the same day's values to be fresh.

Universe: same as backtest_swing_setup.py - active, market_cap >= 2000 Cr,
with an industry that maps to a sector index (scripts/sync_dhan_indices.py's
DHAN_INDICES via app/sector_mapping.py). Unmapped stocks get no sector_score
and therefore no swing_score.
"""
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))
sys.path.append(base_dir)

from app.database import DatabaseManager, StockPerformance
from app.sector_mapping import SECTOR_INDEX_MAP, load_sector_mapped_universe

MIN_MARKET_CAP_CR = float(os.getenv("MIN_MARKET_CAP_CR", 2000))
TREND_TEMPLATE_CRITERIA = 7
STRONG_STOCK_GATE = 50  # at least 4/7 Stage 2 criteria to get a swing_score at all


def compute_strong_stock_scores(session, stock_ids):
    """(criteria passed / 7) * 100 for each stock, based on today's data."""
    start_date = datetime.now() - timedelta(days=500)
    frames = []
    ids = list(stock_ids)
    for i in range(0, len(ids), 200):
        chunk = ids[i : i + 200]
        rows = session.execute(
            text("""
            SELECT stock_id, date, close_price, high_price, low_price
            FROM daily_prices
            WHERE stock_id = ANY(:ids) AND date >= :start_date
            ORDER BY stock_id, date ASC
        """),
            {"ids": chunk, "start_date": start_date},
        ).fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["stock_id", "date", "close", "high", "low"]))

    if not frames:
        return {}

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["stock_id", "date"], keep="last")
    df["date"] = pd.to_datetime(df["date"])

    scores = {}
    for stock_id, g in df.sort_values("date").groupby("stock_id"):
        close, high, low = g["close"], g["high"], g["low"]
        if len(g) < 50:
            continue

        sma_50 = close.rolling(50).mean().iloc[-1]
        sma_150 = close.rolling(150).mean().iloc[-1] if len(g) >= 150 else None
        sma_200 = close.rolling(200).mean().iloc[-1] if len(g) >= 200 else None
        sma_200_series = close.rolling(200).mean()
        sma_200_1m_ago = sma_200_series.iloc[-22] if len(g) >= 222 else None
        current_close = close.iloc[-1]
        high_252 = high.tail(252).max()
        low_252 = low.tail(252).min()

        # The exact 7 pure trend-template criteria from calculate_stage2.py
        # (its cond1 through cond7), minus cond8 (RS rank), which is scored
        # separately elsewhere.
        checks = [
            (current_close > sma_150 and current_close > sma_200)
            if (sma_150 is not None and sma_200 is not None)
            else False,  # cond1
            (sma_150 > sma_200) if (sma_150 is not None and sma_200 is not None) else False,  # cond2
            (sma_200 > sma_200_1m_ago) if (sma_200 is not None and sma_200_1m_ago is not None) else False,  # cond3
            (sma_50 > sma_150 and sma_50 > sma_200)
            if (sma_50 is not None and sma_150 is not None and sma_200 is not None)
            else False,  # cond4
            (current_close > sma_50) if sma_50 is not None else False,  # cond5
            current_close >= 1.30 * low_252,  # cond6
            current_close >= 0.75 * high_252,  # cond7
        ]
        passed = sum(1 for c in checks if c)
        scores[stock_id] = round(passed / TREND_TEMPLATE_CRITERIA * 100, 2)

    return scores


def compute_sector_scores(session, sector_symbols):
    """Percentile rank of 1-month return across the given sector indices."""
    rows = session.execute(
        text("""
        SELECT i.symbol, ip.change_1m
        FROM index_performance ip
        JOIN indices i ON i.id = ip.index_id
        WHERE i.symbol = ANY(:symbols)
    """),
        {"symbols": list(sector_symbols)},
    ).fetchall()

    df = pd.DataFrame(rows, columns=["symbol", "change_1m"]).dropna()
    if df.empty:
        return {}
    df["sector_score"] = df["change_1m"].rank(pct=True) * 100
    return dict(zip(df["symbol"], df["sector_score"].round(2), strict=False))


def calculate_swing_score():
    print("Starting Swing Score Calculation...")
    db = DatabaseManager()
    session = db.Session()

    try:
        universe_df = load_sector_mapped_universe(session, MIN_MARKET_CAP_CR)
        if universe_df.empty:
            print("Empty universe, aborting.")
            return

        stock_ids = universe_df["stock_id"].tolist()
        sector_symbol_map = dict(zip(universe_df["stock_id"], universe_df["sector_symbol"], strict=False))

        print("Computing Strong Stock scores (Stage 2 trend template, partial credit)...")
        strong_stock_scores = compute_strong_stock_scores(session, stock_ids)
        print(f"Computed for {len(strong_stock_scores)} stocks.")

        print("Computing Sector scores (1-month sector index return percentile)...")
        sector_symbols = sorted(set(SECTOR_INDEX_MAP.values()))
        sector_index_scores = compute_sector_scores(session, sector_symbols)

        print("Loading RS rank and ADR% (must already be fresh from calculate_stage2.py / calculate_adr.py)...")
        rows = session.execute(
            text("""
            SELECT stock_id, stage2_rs_rank, adr_pct FROM stock_performance
            WHERE stock_id = ANY(:ids)
        """),
            {"ids": stock_ids},
        ).fetchall()
        rs_adr_df = pd.DataFrame(rows, columns=["stock_id", "rs_rank", "adr_pct"])
        adr_valid = rs_adr_df.dropna(subset=["adr_pct"])
        adr_score_map = dict(
            zip(adr_valid["stock_id"], (adr_valid["adr_pct"].rank(pct=True) * 100).round(2), strict=False)
        )
        rs_score_map = dict(zip(rs_adr_df["stock_id"], rs_adr_df["rs_rank"], strict=False))

        existing_perfs = session.execute(text("SELECT stock_id, id FROM stock_performance")).fetchall()
        existing_map = {p[0]: p[1] for p in existing_perfs}

        updates = []
        for stock_id in stock_ids:
            perf_id = existing_map.get(stock_id)
            if not perf_id:
                continue

            strong_stock_score = strong_stock_scores.get(stock_id)
            sector_symbol = sector_symbol_map.get(stock_id)
            sector_score = sector_index_scores.get(sector_symbol)
            rs_score = rs_score_map.get(stock_id)
            adr_score = adr_score_map.get(stock_id)

            passes_gate = strong_stock_score is not None and strong_stock_score >= STRONG_STOCK_GATE
            components = [rs_score, sector_score, adr_score]
            swing_score = (
                round(sum(components) / 3, 2) if passes_gate and all(c is not None for c in components) else None
            )

            updates.append(
                {
                    "id": perf_id,
                    "strong_stock_score": strong_stock_score,
                    "sector_score": sector_score,
                    "adr_score": adr_score,
                    "swing_score": swing_score,
                }
            )

        if updates:
            print(f"Updating StockPerformance for {len(updates)} records...")
            session.bulk_update_mappings(StockPerformance, updates)
            session.commit()
            complete = sum(1 for u in updates if u["swing_score"] is not None)
            print(f"Database updated successfully. {complete} stocks have a complete swing_score.")

    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    calculate_swing_score()
