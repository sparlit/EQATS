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


# scripts/07_export_bse_unmapped.py
# Exports all incomplete/retryable classifications for BSE fallback processing.


from datetime import UTC, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
INPUT_FILE = PROCESSED / "nse_mainboard_master_bse_classified.parquet"
OUTPUT_FILE = PROCESSED / "nse_bse_unmapped.csv"

RETRYABLE_STATUSES = {"PENDING", "REVIEW_REQUIRED", "NOT_FOUND", "BSE_RETRY"}

REPORT_COLUMNS = [
    "symbol",
    "company_name",
    "series",
    "isin",
    "listing_date",
    "sector",
    "industry",
    "basic_industry",
    "classification_status",
    "classification_source",
    "classification_failure_reason",
    "bse_attempt_count",
    "bse_last_attempt_utc",
    "bse_code",
    "fallback_bse_attempted",
    "yahoo_attempted",
]


def clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def main() -> None:
    if not INPUT_FILE.exists():
        msg = f"Missing classified master file: {INPUT_FILE}"
        raise FileNotFoundError(msg)

    master = pd.read_parquet(INPUT_FILE).copy()
    required = ["symbol", "isin", "classification_status", "sector", "industry", "basic_industry"]
    missing = [column for column in required if column not in master.columns]
    if missing:
        msg = f"Master file missing required columns: {missing}"
        raise ValueError(msg)

    for column in [
        "symbol",
        "company_name",
        "series",
        "isin",
        "classification_status",
        "classification_source",
        "sector",
        "industry",
        "basic_industry",
        "classification_failure_reason",
        "bse_attempt_count",
        "bse_last_attempt_utc",
        "bse_code",
        "fallback_bse_attempted",
        "yahoo_attempted",
    ]:
        if column not in master.columns:
            master[column] = ""
        master[column] = clean_series(master[column])

    hierarchy_complete = master["sector"].ne("") & master["industry"].ne("") & master["basic_industry"].ne("")
    retryable = master["classification_status"].isin(RETRYABLE_STATUSES)
    unmapped = master[~hierarchy_complete & retryable].copy()

    # Avoid blank identity records: they cannot safely be resolved by BSE/Yahoo.
    unmapped = unmapped[(unmapped["symbol"] != "") & (unmapped["isin"] != "")].copy()
    unmapped["report_generated_at_utc"] = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    columns = [column for column in REPORT_COLUMNS if column in unmapped.columns]
    columns.append("report_generated_at_utc")
    unmapped = unmapped[columns].drop_duplicates(subset=["isin"], keep="last")
    unmapped = unmapped.sort_values(["classification_status", "bse_attempt_count", "symbol", "isin"]).reset_index(
        drop=True
    )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    unmapped.to_csv(OUTPUT_FILE, index=False)

    status_counts = master["classification_status"].value_counts(dropna=False).to_dict()
    print("========== CLASSIFICATION EXCEPTION REPORT COMPLETE ==========")
    print(f"Total master records: {len(master):,}")
    print(f"Complete hierarchy records: {int(hierarchy_complete.sum()):,}")
    print(f"Retryable incomplete records exported: {len(unmapped):,}")
    print(f"Status counts: {status_counts}")
    print(f"Saved report: {OUTPUT_FILE}")

    if not unmapped.empty:
        print("\n========== FIRST 25 RETRYABLE RECORDS ==========")
        print(unmapped.head(25).to_string(index=False))


if __name__ == "__main__":
    main()
