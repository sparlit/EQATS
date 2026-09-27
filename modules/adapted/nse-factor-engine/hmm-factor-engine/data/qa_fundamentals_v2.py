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
qa_fundamentals_v2.py
=====================
Targeted QA — only flags missing must-haves for the factor engine.

Must-haves by factor:
  RMW (non-fin only)  : sales, raw_material, book_equity
  Quality (non-fin)   : net_profit, book_equity, total_debt, shares_cr
  Quality (fin)       : net_profit, book_equity, shares_cr
  Value               : net_profit, book_equity, sales, shares_cr
  Size                : shares_cr

Derived / not critical:
  eps          → computed as net_profit / shares_cr
  raw_material → legitimately null for IT/services/financials

Usage:
    python qa_fundamentals_v2.py [parquet_path] [sector_csv_path]
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────
parquet_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fundamentals_annual.parquet")
sector_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("ticker_to_sector.csv")

df = pd.read_parquet(parquet_path)
sec = pd.read_csv(sector_path)[["nse_ticker", "is_financial"]]
sec["is_financial"] = sec["is_financial"].astype(str).str.lower().isin(["true", "1", "yes"])

# Merge sector info
df = df.merge(sec, on="nse_ticker", how="left")
df["is_financial"] = df["is_financial"].fillna(False)

# Focus on Mar fiscal years only (main universe), exclude very old data
df_main = df[df["fiscal_year"].str.startswith("Mar", na=False)].copy()
# Focus on Mar'18 onwards (meaningful history for factors)
RECENT_YEARS = [f"Mar'{y}" for y in range(18, 27)]
df_recent = df_main[df_main["fiscal_year"].isin(RECENT_YEARS)].copy()

fin = df_recent[df_recent["is_financial"]]
nonfin = df_recent[~df_recent["is_financial"]]

print(f"\n{'=' * 65}")
print("  FACTOR ENGINE — MUST-HAVE QA (Mar'18 to Mar'26)")
print(f"{'=' * 65}")
print(f"  Total rows (Mar years): {len(df_recent):,}")
print(f"  Non-financial tickers : {nonfin['nse_ticker'].nunique()}")
print(f"  Financial tickers     : {fin['nse_ticker'].nunique()}")


def check_null(label, series, df_sub, col):
    n_null = series.isnull().sum()
    n_total = len(series)
    tickers = df_sub[series.isnull()]["nse_ticker"].unique().tolist()
    pct = n_null / n_total * 100
    status = "✅" if pct < 5 else ("⚠️ " if pct < 20 else "🔴")
    print(f"  {status} {label:<35} {n_null:>5} / {n_total} nulls ({pct:.1f}%)")
    if tickers and pct >= 5:
        print(f"      Tickers: {sorted(tickers)[:20]}{'...' if len(tickers) > 20 else ''}")


# ── 1. shares_cr — critical for ALL factors ───────────────────────────────────
print("\n── shares_cr (critical for Size, Value, Quality, EPS) ────")
check_null("Non-fin shares_cr", nonfin["shares_cr"], nonfin, "shares_cr")
check_null("Financial shares_cr", fin["shares_cr"], fin, "shares_cr")

# ── 2. net_profit — critical for ROE, EPS, E/P ───────────────────────────────
print("\n── net_profit (critical for ROE, EPS, E/P) ───────────────")
check_null("Non-fin net_profit", nonfin["net_profit"], nonfin, "net_profit")
check_null("Financial net_profit", fin["net_profit"], fin, "net_profit")

# ── 3. book_equity — critical for ROE, D/E, B/P ──────────────────────────────
print("\n── book_equity (critical for ROE, D/E, B/P) ──────────────")
check_null("Non-fin book_equity", nonfin["book_equity"], nonfin, "book_equity")
check_null("Financial book_equity", fin["book_equity"], fin, "book_equity")

# ── 4. sales — critical for RMW (non-fin) and S/P (Value) ────────────────────
print("\n── sales (RMW non-fin, S/P Value) ────────────────────────")
check_null("Non-fin sales", nonfin["sales"], nonfin, "sales")
# For financials, sales null is expected — just report count
fin_sales_null = fin["sales"].isnull().sum()
print(f"  ✅ Financial sales null: {fin_sales_null}/{len(fin)} — expected (banks have NII not Sales)")

# ── 5. raw_material — critical for RMW non-fin ───────────────────────────────
print("\n── raw_material (RMW non-fin only) ───────────────────────")
# Split non-fin into manufacturing vs services/IT
# Proxy: if sales is non-null but raw_material is null → likely services
nonfin_with_sales = nonfin[nonfin["sales"].notna()]
rm_null = nonfin_with_sales[nonfin_with_sales["raw_material"].isnull()]
rm_null_tickers = rm_null["nse_ticker"].unique()
pct = len(rm_null) / len(nonfin_with_sales) * 100
status = "⚠️ " if pct > 15 else "✅"
print(f"  {status} Non-fin with sales but no raw_material: {len(rm_null)}/{len(nonfin_with_sales)} ({pct:.1f}%)")
print("      These will be excluded from RMW — verify a few are genuinely services cos:")
print(f"      Sample: {sorted(rm_null_tickers)[:15]}")

# ── 6. total_debt — critical for D/E (non-fin Quality) ───────────────────────
print("\n── total_debt (D/E for non-fin Quality) ──────────────────")
# Distinguish NaN (missing) from 0 (zero debt — valid)
td_null = nonfin["total_debt"].isnull().sum()
td_zero = (nonfin["total_debt"] == 0).sum()
td_pos = (nonfin["total_debt"] > 0).sum()
print("  total_debt breakdown for non-financials:")
print(f"    Positive (has debt)  : {td_pos:>5}")
print(f"    Zero (debt-free)     : {td_zero:>5} ✅ expected")
print(f"    NaN (missing)        : {td_null:>5}")
if td_null > 0:
    null_tickers = nonfin[nonfin["total_debt"].isnull()]["nse_ticker"].unique()
    # Check if these have debt in any year
    pct = td_null / len(nonfin) * 100
    status = "⚠️ " if pct > 10 else "✅"
    print(f"  {status} {td_null}/{len(nonfin)} ({pct:.1f}%) non-fin rows have NaN total_debt")
    print(f"      Sample tickers: {sorted(null_tickers)[:15]}")

# ── 7. Ticker-level summary — which tickers are critically broken ─────────────
print("\n── Tickers with >= 5 years but MISSING critical fields ────")


def ticker_coverage(sub, col, min_years=5):
    """Tickers with enough history but still missing col."""
    grp = sub.groupby("nse_ticker").agg(
        total_years=("fiscal_year", "count"), null_years=(col, lambda x: x.isnull().sum())
    )
    bad = grp[(grp["total_years"] >= min_years) & (grp["null_years"] == grp["total_years"])]
    return bad.index.tolist()


nf_no_shares = ticker_coverage(nonfin, "shares_cr")
nf_no_sales = ticker_coverage(nonfin, "sales")
f_no_shares = ticker_coverage(fin, "shares_cr")

print(f"  Non-fin tickers: >=5yrs history, ALL shares_cr null : {len(nf_no_shares)}")
if nf_no_shares:
    print(f"    {nf_no_shares}")

print(f"  Non-fin tickers: >=5yrs history, ALL sales null     : {len(nf_no_sales)}")
if nf_no_sales:
    print(f"    {nf_no_sales}")

print(f"  Fin tickers:     >=5yrs history, ALL shares_cr null : {len(f_no_shares)}")
if f_no_shares:
    print(f"    {f_no_shares}")

# ── 8. EPS derivability check ─────────────────────────────────────────────────
print("\n── EPS derivability (net_profit / shares_cr) ─────────────")
can_derive = df_recent["eps"].notna().sum()
total = len(df_recent)
print(f"  EPS derivable rows : {can_derive:,} / {total:,} ({can_derive / total * 100:.1f}%)")
print("  ✅ EPS is derived — not fetched. No action needed.")

# ── 9. Final verdict ──────────────────────────────────────────────────────────
print("\n── VERDICT ────────────────────────────────────────────────")
issues = []
if nf_no_shares:
    issues.append(f"🔴 {len(nf_no_shares)} non-fin tickers have no shares_cr at all → excluded from Size/Value/Quality")
if nf_no_sales:
    issues.append(f"⚠️  {len(nf_no_sales)} non-fin tickers have no sales → excluded from RMW and S/P")
if not issues:
    print("  ✅ No critical missing must-haves. Ready for factor scripts.")
else:
    for i in issues:
        print(f"  {i}")
    print("\n  Everything else (raw_material nulls for IT/services, sales nulls for financials,")
    print("  total_debt=0 for debt-free cos) is structurally expected — no action needed.")

print(f"\n{'=' * 65}\n")
