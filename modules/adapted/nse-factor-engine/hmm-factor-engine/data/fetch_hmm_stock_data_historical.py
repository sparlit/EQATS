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
fetch_hmm_stock_data_historical.py
===================================
Master production script for daily stock OHLCV data.

Universe
--------
Union of current members from the 4 index symbol CSVs:
  /home/ec2-user/nse-factor-engine/nifty500_symbols.csv
  /home/ec2-user/nse-factor-engine/nifty100_symbols.csv
  /home/ec2-user/nse-factor-engine/niftymidcap150_symbols.csv
  /home/ec2-user/nse-factor-engine/niftysmallcap250_symbols.csv

Behaviour
---------
  - Incremental: fetches only new dates since last saved date
  - Maintains rolling 240-month window: drops rows older than today - 240 months
  - Corporate action check: 1-day drop >40% + volume spike >40% (last 24 months only)
    -> if detected: refetch full price history for that symbol
    -> if specific bad date still present after refetch: null out that row only
    -> bad (symbol, date) pairs saved to corporate_action_flags.parquet
    -> symbol is NEVER permanently excluded — only bad rows are nulled
  - On load: bad dates from flags file are re-applied (nulled) automatically
  - shares_outstanding: fetched only on first run or for new symbols
    -> saved to shares_outstanding.parquet as static lookup
  - New symbols: fetched from WINDOW_START, shares_outstanding fetched too

Output
------
  hmm-factor-engine/data/prices_hmm_daily.parquet
    Long format: symbol | date | open | high | low | close | volume
  hmm-factor-engine/data/prices_hmm_daily_volume.parquet
    Wide format: date (index) x symbol (columns), values = daily volume
  hmm-factor-engine/data/shares_outstanding.parquet
    symbol | shares_outstanding
  hmm-factor-engine/data/corporate_action_flags.parquet
    symbol | bad_date | reason

Usage
-----
  python3 hmm-factor-engine/data/fetch_hmm_stock_data_historical.py
"""

import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE = Path("/home/ec2-user/nse-factor-engine")
WINDOW_MONTHS = 240
BATCH_SIZE = 20
SLEEP_BETWEEN = 2
RETRY_SLEEP = 5

DAILY_DROP_THRESHOLD = 0.40  # 1-day close-to-close drop; >40% = data error given NSE circuits
VOLUME_SPIKE_THRESHOLD = 0.40  # volume must also spike to confirm
CA_LOOKBACK_MONTHS = 24  # only check last 24 months — ignores genuine historical crashes

UNIVERSE_FILES = [
    BASE / "nifty500_symbols.csv",
    BASE / "nifty100_symbols.csv",
    BASE / "niftymidcap150_symbols.csv",
    BASE / "niftysmallcap250_symbols.csv",
]

OUTPUT_DIR = Path(__file__).parent
PRICE_FILE = OUTPUT_DIR / "prices_hmm_daily.parquet"
VOLUME_FILE = OUTPUT_DIR / "prices_hmm_daily_volume.parquet"
SHARES_FILE = OUTPUT_DIR / "shares_outstanding.parquet"
FLAGS_FILE = OUTPUT_DIR / "corporate_action_flags.parquet"

TODAY = date.today()
END_DATE = TODAY.strftime("%Y-%m-%d")
WINDOW_START = TODAY - relativedelta(months=WINDOW_MONTHS)
WINDOW_START_STR = WINDOW_START.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Flags helpers
# ---------------------------------------------------------------------------
def load_flags() -> pd.DataFrame:
    """
    Load corporate_action_flags.parquet.
    Schema: symbol | bad_date | reason
    Returns empty DataFrame with correct schema if file missing or old schema.
    """
    schema = pd.DataFrame(columns=["symbol", "bad_date", "reason"])
    if not FLAGS_FILE.exists():
        return schema
    df = pd.read_parquet(FLAGS_FILE)
    df.columns = df.columns.str.strip().str.lower()
    # Migrate old schema (symbol | reason only) to new schema
    if "bad_date" not in df.columns:
        print("  Migrating corporate_action_flags.parquet to new schema (adding bad_date)...")
        df["bad_date"] = pd.NaT
        df = df[["symbol", "bad_date", "reason"]]
        df.to_parquet(FLAGS_FILE, index=False)
        print(f"  Migrated {len(df)} rows")
    df["bad_date"] = pd.to_datetime(df["bad_date"])
    return df


def save_flags(flags: pd.DataFrame) -> None:
    flags = flags.drop_duplicates(subset=["symbol", "bad_date"], keep="last")
    flags.to_parquet(FLAGS_FILE, index=False)
    print(f"  Saved corporate_action_flags.parquet — {len(flags)} bad (symbol, date) pairs")


def apply_flags(prices: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """
    Null out close/open/high/low/volume for any (symbol, bad_date) in flags.
    Symbol stays in the dataframe — only the bad row is nulled.
    """
    if flags.empty:
        return prices
    bad = flags.dropna(subset=["bad_date"])
    if bad.empty:
        return prices
    prices = prices.copy()
    for _, row in bad.iterrows():
        mask = (prices["symbol"] == row["symbol"]) & (prices["date"] == row["bad_date"])
        if mask.any():
            prices.loc[mask, ["open", "high", "low", "close", "volume"]] = None
    nulled = len(bad)
    print(f"  Applied {nulled} bad-date null(s) from flags file")
    return prices


# ---------------------------------------------------------------------------
# Step 1 — Load universe
# ---------------------------------------------------------------------------
def load_universe() -> list:
    all_symbols = set()
    for f in UNIVERSE_FILES:
        df = pd.read_csv(f)
        df.columns = df.columns.str.strip().str.lower()
        syms = df["symbol"].dropna().str.strip().tolist()
        all_symbols.update(syms)
        print(f"  {f.name}: {len(syms)} symbols")
    tickers = sorted(all_symbols)
    print(f"  Total unique symbols: {len(tickers)}")
    return tickers


# ---------------------------------------------------------------------------
# Step 2 — Load existing data
# ---------------------------------------------------------------------------
def load_existing_prices(flags: pd.DataFrame) -> pd.DataFrame:
    """
    Load prices parquet and re-apply bad-date nulls from flags.
    No symbol is excluded — only specific bad rows are nulled.
    """
    if PRICE_FILE.exists():
        df = pd.read_parquet(PRICE_FILE)
        df.columns = df.columns.str.strip().str.lower()
        df["date"] = pd.to_datetime(df["date"])
        print(
            f"  Existing prices: {df.shape[0]} rows, "
            f"{df['symbol'].nunique()} symbols, "
            f"{df['date'].min().date()} -> {df['date'].max().date()}"
        )
        return apply_flags(df, flags)
    print("  No existing prices found — full fetch for all symbols")
    return pd.DataFrame()


def load_existing_shares() -> pd.DataFrame:
    if SHARES_FILE.exists():
        df = pd.read_parquet(SHARES_FILE)
        df.columns = df.columns.str.strip().str.lower()
        print(f"  Existing shares_outstanding: {len(df)} symbols")
        return df
    print("  No existing shares_outstanding found")
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Step 3 — Fetch OHLCV in batches, return long format
# ---------------------------------------------------------------------------
def fetch_ohlcv(tickers_ns: list, start: str, end: str) -> pd.DataFrame:
    raw = yf.download(
        tickers_ns,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns.names = ["field", "ticker"]
        df = raw.stack(level="ticker", future_stack=True).reset_index()
        df.columns = df.columns.str.strip().str.lower()
        df = df.rename(columns={"ticker": "symbol"})
    else:
        df = raw.reset_index()
        df.columns = df.columns.str.strip().str.lower()
        df["symbol"] = tickers_ns[0].replace(".NS", "")

    df["symbol"] = df["symbol"].str.replace(".NS", "", regex=False)
    df["date"] = pd.to_datetime(df["date"])

    cols = ["symbol", "date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]]
    df = df.dropna(subset=["close"])
    df = df[df["volume"] > 0]

    return df


# ---------------------------------------------------------------------------
# Step 4 — Corporate action detection
# ---------------------------------------------------------------------------
def detect_corporate_actions(prices: pd.DataFrame) -> list:
    """
    Detect likely yfinance data errors in the last 24 months.

    Logic:
      - 1-day close-to-close drop >40%: NSE circuits cap moves at 10-20%
        for large caps, so a 40% single-day drop is almost certainly a
        data error, not a real market move.
      - Volume spike >40% as confirmation.
      - Only checks last 24 months — genuine crashes (2008, 2020) are
        outside this window and will never be flagged.

    Returns list of (symbol, bad_date) tuples.
    """
    lookback_cutoff = pd.Timestamp(date.today() - relativedelta(months=CA_LOOKBACK_MONTHS))
    flagged = []

    for sym, grp in prices.groupby("symbol"):
        grp = grp.sort_values("date").set_index("date")
        grp = grp[grp.index >= lookback_cutoff]
        if len(grp) < 10:
            continue

        # Skip rows already nulled by flags
        grp = grp.dropna(subset=["close"])

        daily_ret = grp["close"].pct_change(1)
        vol_roll = grp["volume"].rolling(5).sum()
        vol_ratio = (vol_roll / vol_roll.shift(5)) - 1
        flag = (daily_ret < -DAILY_DROP_THRESHOLD) & (vol_ratio > VOLUME_SPIKE_THRESHOLD)

        if flag.any():
            bad_dates = grp.index[flag].tolist()
            for bad_date in bad_dates:
                ret = daily_ret[bad_date]
                print(f"  CORP ACTION FLAG: {sym}  {bad_date.date()}  1-day ret={ret:.1%}")
                flagged.append((sym, bad_date))

    return flagged


# ---------------------------------------------------------------------------
# Step 5 — Fetch shares_outstanding
# ---------------------------------------------------------------------------
def fetch_shares_outstanding(symbols: list) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        try:
            info = yf.Ticker(f"{sym}.NS").info
            shares = info.get("sharesOutstanding")
            rows.append({"symbol": sym, "shares_outstanding": shares})
            status = f"{shares:,.0f}" if shares else "N/A"
            print(f"  {sym}: {status}")
        except Exception as e:
            rows.append({"symbol": sym, "shares_outstanding": None})
            print(f"  {sym}: ERROR — {e}")
        time.sleep(0.3)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 6 — Build and save wide volume parquet
# ---------------------------------------------------------------------------
def save_volume_parquet(combined: pd.DataFrame) -> None:
    volume = (
        combined[["symbol", "date", "volume"]]
        .dropna(subset=["volume"])
        .pivot(index="date", columns="symbol", values="volume")
    )
    volume.index.name = None
    volume.columns.name = None
    volume.to_parquet(VOLUME_FILE)
    print(f"  Saved volume : {volume.shape} -> {VOLUME_FILE.name}")
    print(f"  Date range   : {volume.index.min().date()} -> {volume.index.max().date()}")
    print(f"  Tickers      : {volume.shape[1]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("HMM Stock Data Fetch — Production")
    print(f"Run date      : {END_DATE}")
    print(f"Window start  : {WINDOW_START_STR}  ({WINDOW_MONTHS} months)")
    print("=" * 60)

    # ── Load universe ─────────────────────────────────────────────
    print("\n[1/6] Loading universe...")
    tickers = load_universe()
    [f"{t}.NS" for t in tickers]

    # ── Load flags ────────────────────────────────────────────────
    print("\n[2/6] Loading flags and existing data...")
    flags = load_flags()
    print(f"  Bad date flags loaded: {len(flags)}")
    existing_prices = load_existing_prices(flags)
    existing_shares = load_existing_shares()

    # ── Determine fetch window and new symbols ────────────────────
    print("\n[3/6] Determining fetch window and new symbols...")
    if not existing_prices.empty:
        last_date = existing_prices["date"].max().date()
        fetch_start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        existing_syms = set(existing_prices["symbol"].unique())
        new_syms = [t for t in tickers if t not in existing_syms]
        print(f"  Last date in parquet  : {last_date}")
        print(f"  Incremental fetch from: {fetch_start}")
        print(f"  New symbols           : {len(new_syms)}")
    else:
        fetch_start = WINDOW_START_STR
        new_syms = tickers
        print(f"  Full fetch from: {fetch_start}")

    # ── Fetch prices ──────────────────────────────────────────────
    print("\n[4/6] Fetching prices...")
    all_parts = []
    failed = []

    # Full history for new symbols
    if new_syms:
        print(f"  Fetching full history for {len(new_syms)} new symbols...")
        new_ns = [f"{s}.NS" for s in new_syms]
        for i in range(0, len(new_ns), BATCH_SIZE):
            batch = new_ns[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_b = (len(new_ns) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"  New batch {batch_num}/{total_b}: {len(batch)} tickers")
            df = fetch_ohlcv(batch, WINDOW_START_STR, END_DATE)
            if df.empty:
                failed.extend([t.replace(".NS", "") for t in batch])
            else:
                print(f"    OK: {df['symbol'].nunique()} tickers, {len(df)} rows")
                all_parts.append(df)
            time.sleep(SLEEP_BETWEEN)

    # Incremental fetch for existing symbols
    if fetch_start < END_DATE:
        existing_ns = [f"{t}.NS" for t in tickers if t not in new_syms]
        for i in range(0, len(existing_ns), BATCH_SIZE):
            batch = existing_ns[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_b = (len(existing_ns) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"  Incremental batch {batch_num}/{total_b}: {len(batch)} tickers")
            df = fetch_ohlcv(batch, fetch_start, END_DATE)
            if df.empty:
                failed.extend([t.replace(".NS", "") for t in batch])
            else:
                print(f"    OK: {df['symbol'].nunique()} tickers, {len(df)} rows")
                all_parts.append(df)
            time.sleep(SLEEP_BETWEEN)

    # Retry failed
    if failed:
        print(f"\n  Retrying {len(failed)} failed tickers solo...")
        for sym in failed:
            print(f"    {sym}...")
            time.sleep(RETRY_SLEEP)
            start = WINDOW_START_STR if sym in new_syms else fetch_start
            df = fetch_ohlcv([f"{sym}.NS"], start, END_DATE)
            if not df.empty:
                all_parts.append(df)
                print("    OK")
            else:
                print(f"    STILL EMPTY — skipping {sym}")

    # ── Merge + corporate action check ────────────────────────────
    print("\n[5/6] Corporate action check + merge...")
    if all_parts:
        new_data = pd.concat(all_parts, ignore_index=True)

        if not existing_prices.empty:
            combined = pd.concat([existing_prices, new_data], ignore_index=True)
            combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")
        else:
            combined = new_data

        combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)

        # Corporate action detection — returns (symbol, bad_date) pairs
        print("  Running corporate action check...")
        flagged_pairs = detect_corporate_actions(combined)

        if flagged_pairs:
            unique_syms = list({s for s, _ in flagged_pairs})
            print(f"  {len(flagged_pairs)} bad date(s) across {len(unique_syms)} symbol(s) — refetching...")

            # Refetch full history for affected symbols
            refetch_parts = []
            for sym in unique_syms:
                time.sleep(RETRY_SLEEP)
                df = fetch_ohlcv([f"{sym}.NS"], WINDOW_START_STR, END_DATE)
                if not df.empty:
                    refetch_parts.append(df)
                    print(f"    {sym}: refetched {len(df)} rows")

            if refetch_parts:
                refetch_data = pd.concat(refetch_parts, ignore_index=True)
                combined = combined[~combined["symbol"].isin(unique_syms)]
                combined = pd.concat([combined, refetch_data], ignore_index=True)
                combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)

            # Re-check after refetch — if bad date still present, null it out
            print("  Re-checking after refetch...")
            still_flagged = detect_corporate_actions(combined[combined["symbol"].isin(unique_syms)])

            if still_flagged:
                print(f"  {len(still_flagged)} bad date(s) persist after refetch — nulling rows:")
                for sym, bad_date in still_flagged:
                    mask = (combined["symbol"] == sym) & (combined["date"] == bad_date)
                    combined.loc[mask, ["open", "high", "low", "close", "volume"]] = None
                    print(f"    Nulled: {sym}  {bad_date.date()}")

                # Save to flags file
                new_flag_rows = pd.DataFrame(
                    [{"symbol": s, "bad_date": d, "reason": "yfinance_unadjusted"} for s, d in still_flagged]
                )
                updated_flags = pd.concat([flags, new_flag_rows], ignore_index=True)
                save_flags(updated_flags)
            else:
                print("  All flagged symbols look clean after refetch.")

        else:
            print("  No corporate action artifacts detected.")

        # Drop rows outside rolling window
        cutoff = pd.Timestamp(WINDOW_START)
        before = len(combined)
        combined = combined[combined["date"] >= cutoff]
        dropped = before - len(combined)
        if dropped > 0:
            print(f"  Dropped {dropped} rows older than {WINDOW_START_STR}")

        combined.to_parquet(PRICE_FILE, index=False)
        print(f"  Saved prices : {combined.shape} -> {PRICE_FILE.name}")
        print(f"  Date range   : {combined['date'].min().date()} -> {combined['date'].max().date()}")
        print(f"  Symbols      : {combined['symbol'].nunique()}")

        save_volume_parquet(combined)

    else:
        print("  No new price data fetched.")

    # ── Shares outstanding ────────────────────────────────────────
    print("\n[6/6] Shares outstanding...")
    known_syms = set(existing_shares["symbol"].tolist()) if not existing_shares.empty else set()
    missing_syms = [t for t in tickers if t not in known_syms]

    if missing_syms:
        print(f"  Fetching shares_outstanding for {len(missing_syms)} symbols...")
        new_shares_df = fetch_shares_outstanding(missing_syms)
        if not existing_shares.empty:
            existing_shares = pd.concat([existing_shares, new_shares_df], ignore_index=True)
        else:
            existing_shares = new_shares_df
        existing_shares = existing_shares.drop_duplicates(subset=["symbol"], keep="last")
        existing_shares.to_parquet(SHARES_FILE, index=False)
        print(f"  Saved shares_outstanding: {len(existing_shares)} symbols -> {SHARES_FILE.name}")
    else:
        print("  All symbols already have shares_outstanding. No fetch needed.")

    print("\n" + "=" * 60)
    print("Done.")
    print("=" * 60)


if __name__ == "__main__":
    main()
