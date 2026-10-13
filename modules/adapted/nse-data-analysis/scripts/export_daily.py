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


#!/usr/bin/env python3
"""
scripts/export_daily.py
========================
Headless (no Streamlit UI) version of the screener pipeline, designed to run
on a schedule — e.g. via GitHub Actions — and write a fresh data/exports/latest.json
that an external website can fetch.

Usage:
    python scripts/export_daily.py --universe NIFTY500 --max-stocks 500
    python scripts/export_daily.py --universe NIFTY50           # faster test run
    python scripts/export_daily.py --symbols RELIANCE,TCS,INFY  # custom list

This script intentionally reuses the exact same utils/ modules as the Streamlit
app (data_fetcher, trend_analysis, valuation, scoring_engine, exporter) so the
scheduled export and the interactive app can never silently drift apart in logic.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from utils.data_fetcher import YFinanceSource, _load_universe_impl, fetch_universe
from utils.exporter import write_export, write_export_csv
from utils.peer_comparison import attach_peer_context
from utils.scoring_engine import composite_score, safe
from utils.trend_analysis import compute_trends
from utils.valuation import blended_intrinsic_value, graham_number, relative_valuation, simple_dcf


def run_pipeline(
    symbols: list[str], universe_label: str, use_cache: bool = True
) -> tuple[pd.DataFrame, dict, list]:
    print(f"Fetching {len(symbols)} symbols...")

    source = YFinanceSource()

    def _progress(done, total, symbol):
        if done % 10 == 0 or done == total:
            print(f"  [{done}/{total}] {symbol}")

    fetch_results = fetch_universe(
        symbols, source=source, progress_callback=_progress, use_cache=use_cache
    )

    rows = []
    failures = []
    deep_data = {}

    print("Scoring...")
    for symbol in symbols:
        fr = fetch_results[symbol]
        if not fr.ok:
            failures.append((symbol, fr.error))
            continue

        info = fr.info
        trends = compute_trends(fr.financials)
        dcf = simple_dcf(fr.cashflow, info, growth_rate_yr1_5=trends.get("revenue_cagr"))
        graham = graham_number(info)
        relative = relative_valuation(info, None, None)
        blended = blended_intrinsic_value(dcf, graham, relative)

        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        if blended.get("blended_value") and current_price:
            blended["upside_pct"] = round(
                (blended["blended_value"] - current_price) / current_price * 100, 1
            )
        else:
            blended["upside_pct"] = None

        result = composite_score(info, fr.financials, blended)

        rows.append(
            {
                "Symbol": symbol,
                "Company": info.get("longName", symbol),
                "Sector": info.get("sector", "Unknown"),
                "Industry": info.get("industry", "Unknown"),
                "Price": current_price,
                "PE": info.get("trailingPE"),
                "PB": info.get("priceToBook"),
                "ROE %": round(safe(info.get("returnOnEquity")) * 100, 2),
                "Debt/Equity": info.get("debtToEquity"),
                "Profit Margin %": round(safe(info.get("profitMargins")) * 100, 2),
                "Revenue CAGR %": round(trends.get("revenue_cagr"), 1)
                if trends.get("revenue_cagr") is not None
                else None,
                "Net Income CAGR %": round(trends.get("net_income_cagr"), 1)
                if trends.get("net_income_cagr") is not None
                else None,
                "Margin Trend": trends.get("margin_trend"),
                "Blended Fair Value": blended.get("blended_value"),
                "Est. Upside %": blended.get("upside_pct"),
                "Valuation Models Used": blended.get("models_used"),
                "Score": result["total_score"],
                "Rating": result["rating"],
                "Valuation Pillar": result["pillar_scores"]["Valuation"],
                "Profitability Pillar": result["pillar_scores"]["Profitability"],
                "Stability Pillar": result["pillar_scores"]["Stability"],
                "Growth Pillar": result["pillar_scores"]["Growth"],
                "Upside Pillar": result["pillar_scores"]["Valuation Upside"],
                "Strengths": ", ".join(result["notes"][:4]),
            }
        )

        deep_data[symbol] = {
            "info": info,
            "trends": trends,
            "dcf": dcf,
            "graham": graham,
            "relative": relative,
            "blended": blended,
            "result": result,
            "fetch": fr,
        }

    if not rows:
        print("ERROR: No data fetched for any symbol.")
        return pd.DataFrame(), {}, failures

    df = pd.DataFrame(rows)

    # Second pass: sector-relative valuation refinement (same as app/main.py)
    sector_medians_pe = df.groupby("Sector")["PE"].median()
    sector_medians_pb = df.groupby("Sector")["PB"].median()

    for symbol in df["Symbol"]:
        d = deep_data[symbol]
        sector = d["info"].get("sector")
        med_pe = sector_medians_pe.get(sector)
        med_pb = sector_medians_pb.get(sector)
        d["relative"] = relative_valuation(d["info"], med_pe, med_pb)
        d["blended"] = blended_intrinsic_value(d["dcf"], d["graham"], d["relative"])
        current_price = d["info"].get("currentPrice") or d["info"].get("regularMarketPrice")
        if d["blended"].get("blended_value") and current_price:
            d["blended"]["upside_pct"] = round(
                (d["blended"]["blended_value"] - current_price) / current_price * 100, 1
            )
        d["result"] = composite_score(
            d["info"], d["fetch"].financials, d["blended"], sector_median_pe=med_pe
        )

    df["Score"] = df["Symbol"].map(lambda s: deep_data[s]["result"]["total_score"])
    df["Rating"] = df["Symbol"].map(lambda s: deep_data[s]["result"]["rating"])
    df["Blended Fair Value"] = df["Symbol"].map(
        lambda s: deep_data[s]["blended"].get("blended_value")
    )
    df["Est. Upside %"] = df["Symbol"].map(lambda s: deep_data[s]["blended"].get("upside_pct"))

    df = attach_peer_context(df)
    df = df.sort_values("Score", ascending=False).reset_index(drop=True)

    return df, deep_data, failures


def main():
    parser = argparse.ArgumentParser(description="Headless fundamental screener export")
    parser.add_argument("--universe", choices=["NIFTY50", "NIFTY500"], default="NIFTY500")
    parser.add_argument(
        "--max-stocks",
        type=int,
        default=None,
        help="Cap the number of stocks (default: all in universe)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated custom symbol list (overrides --universe)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore the 6-hour disk cache and refetch everything",
    )
    parser.add_argument("--output-dir", type=str, default="data/exports")
    args = parser.parse_args()

    start = time.time()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        universe_label = "Custom"
    else:
        universe_df = _load_universe_impl(args.universe)
        symbols = universe_df["Symbol"].tolist()
        if args.max_stocks:
            symbols = symbols[: args.max_stocks]
        universe_label = args.universe

    df, deep_data, failures = run_pipeline(symbols, universe_label, use_cache=not args.no_cache)

    if df.empty:
        print("No data — aborting export.")
        sys.exit(1)

    json_path = write_export(
        df, deep_data, universe_label, output_path=Path(args.output_dir) / "latest.json"
    )
    csv_path = write_export_csv(df, output_path=Path(args.output_dir) / "latest.csv")

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s.")
    print(f"  {len(df)} stocks succeeded, {len(failures)} failed.")
    print(f"  JSON: {json_path}")
    print(f"  CSV:  {csv_path}")

    if failures:
        print(f"\nFailed symbols ({len(failures)}):")
        for sym, err in failures[:20]:
            print(f"  - {sym}: {err}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more")


if __name__ == "__main__":
    main()
