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
main.py
=======
NSE Fundamental Analysis PRO — Enterprise Screener
Entry point. Run with: streamlit run app/main.py
"""

import sys
from pathlib import Path

# Make `utils/` importable when run as `streamlit run app/main.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from utils.analyzer import analyze_stock, refine_with_sector_context
from utils.data_fetcher import YFinanceSource, fetch_universe, load_universe
from utils.exporter import (
    add_single_stock_to_export,
    build_export_payload,
    load_existing_export,
)
from utils.peer_comparison import attach_peer_context, compute_sector_medians, get_sector_median
from utils.scoring_engine import safe

st.set_page_config(
    page_title="NSE Fundamental Screener PRO",
    page_icon="📊",
    layout="wide",
)

st.title("📊 NSE Fundamental Analysis — Enterprise Screener")
st.caption(
    "Full-universe fundamental screening: valuation, profitability, stability, "
    "multi-year growth trends, DCF/intrinsic value, and sector peer comparison."
)

with st.expander("ℹ️ Methodology & honest limitations — please read before trusting the scores"):
    st.markdown(
        """
**Data source:** Yahoo Finance (`yfinance`), an unofficial API. It is generally reliable for
large/mid-cap NSE stocks but can have missing fields, especially for banks/NBFCs
(different statement structure) and recently-listed companies (short history).

**Scoring (0-100):** Five weighted pillars — Valuation (20), Profitability (20),
Stability (20), Growth & Trend (25), Valuation Upside (15). Each pillar is shown
separately in the deep-dive view so the total is never a black box.

**Intrinsic value / DCF:** Built from 2-4 years of public cash flow data with generic
growth/discount-rate assumptions. This is a *directional estimate*, not a price target.
Treat "undervalued by X%" as "worth a closer look," not as investment advice.

**This tool is for research/educational purposes only and is not investment advice.**
        """
    )

tab_screener, tab_search = st.tabs(
    ["📋 Bulk Screener (Nifty 50/500)", "🔎 Single Stock Search (any NSE symbol)"]
)

with tab_search:
    st.markdown(
        "Look up **any NSE-listed symbol**, including ones outside the Nifty 500 list "
        "(small-caps, recent listings, etc). The result is analyzed with the same scoring "
        "engine as the bulk screener, and can be merged into the shared `latest.json` export "
        "so your other site picks it up too — without affecting any of the other stocks already in that file."
    )

    search_symbol = (
        st.text_input(
            "NSE Symbol (no .NS suffix)",
            value="",
            placeholder="e.g. RAINBOW, CAMS, KFINTECH...",
            key="single_search_input",
        )
        .strip()
        .upper()
    )

    search_clicked = st.button("🔍 Analyze this stock", type="primary", key="single_search_button")

    if search_clicked and search_symbol:
        with st.spinner(f"Fetching {search_symbol}..."):
            source = YFinanceSource()
            fr = source.fetch(search_symbol, use_cache=True)

        if not fr.ok:
            st.error(f"Could not fetch data for **{search_symbol}**: {fr.error}")
            st.caption(
                "Common causes: typo in the symbol, a very recently listed company, "
                "or a temporary yfinance rate limit — try again in a moment."
            )
        else:
            analysis = analyze_stock(search_symbol, fr)  # no sector medians yet — standalone lookup
            if analysis is None:
                st.error(
                    "Fetch succeeded but analysis failed unexpectedly — this shouldn't happen; please report it."
                )
            else:
                st.session_state["single_search_result"] = {"symbol": search_symbol, **analysis}

    if "single_search_result" in st.session_state:
        sr = st.session_state["single_search_result"]
        symbol = sr["symbol"]
        row = sr["row"]
        deep = sr["deep"]
        info = deep["info"]
        result = deep["result"]
        trends = deep["trends"]
        dcf = deep["dcf"]
        graham = deep["graham"]

        st.divider()
        st.markdown(f"### {info.get('longName', symbol)} ({symbol})")
        st.caption(f"{row['Sector']} | {row['Industry']}")

        pillar_cols = st.columns(5)
        pillars = result["pillar_scores"]
        for col, (name, val) in zip(pillar_cols, pillars.items(), strict=False):
            max_val = {
                "Valuation": 20,
                "Profitability": 20,
                "Stability": 20,
                "Growth": 25,
                "Valuation Upside": 15,
            }[name]
            col.metric(name, f"{val}/{max_val}")

        st.markdown(f"**Overall Score: {result['total_score']}/100 — {result['rating']}**")
        st.caption(
            "⚠️ No sector peer group available for a standalone lookup, so the Valuation and "
            "Valuation Upside pillars rely on absolute thresholds only (no sector-relative "
            "comparison) — scores may shift slightly if this stock is later included in a bulk run."
        )

        with st.expander("📌 Score notes"):
            for n in result["notes"]:
                st.write(f"- {n}")

        vcol1, vcol2, vcol3, vcol4 = st.columns(4)
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        vcol1.metric("Current Price", f"₹{current_price:.2f}" if current_price else "—")
        if dcf.get("fair_value_per_share"):
            vcol2.metric("DCF Fair Value", f"₹{dcf['fair_value_per_share']:.2f}")
            if dcf.get("warning"):
                vcol2.caption(f"⚠️ {dcf['warning']}")
        else:
            vcol2.metric("DCF Fair Value", "N/A")
            if dcf.get("warning"):
                vcol2.caption(dcf["warning"])
        if graham.get("graham_value"):
            vcol3.metric("Graham Number", f"₹{graham['graham_value']:.2f}")
        else:
            vcol3.metric("Graham Number", "N/A")
        blended = deep["blended"]
        if blended.get("blended_value"):
            vcol4.metric(
                "Blended Fair Value",
                f"₹{blended['blended_value']:.2f}",
                f"{blended.get('upside_pct', 0):.1f}%"
                if blended.get("upside_pct") is not None
                else None,
            )
        else:
            vcol4.metric("Blended Fair Value", "N/A")

        st.divider()
        save_col1, save_col2 = st.columns([1, 2])
        with save_col1:
            save_clicked = st.button(
                "💾 Add to shared export (latest.json)", key="single_search_save"
            )
        with save_col2:
            st.caption(
                "Merges this stock into `data/exports/latest.json` without affecting any other "
                "stocks already in that file. If this symbol is already there from a bulk run, "
                "this updates it; if it's new (e.g. outside Nifty 500), it's added alongside the rest."
            )

        if save_clicked:
            try:
                existing = load_existing_export()
                was_existing = (
                    existing is not None and "stocks" in existing and symbol in existing["stocks"]
                )
                path = add_single_stock_to_export(row, deep)
                if was_existing:
                    st.success(f"Updated **{symbol}**'s entry in `{path}`.")
                else:
                    st.success(
                        f"Added **{symbol}** to `{path}` — now included alongside your bulk-run stocks."
                    )
            except Exception as e:
                st.error(f"Could not write to the export file: {e}")
                st.caption(
                    "If you're running this locally, check that the `data/exports/` folder is "
                    "writable. On Streamlit Cloud, the filesystem resets on redeploy — for a "
                    "persistent feed, run this save step via a workflow that commits to GitHub "
                    "(see README 'Exporting for external consumption')."
                )

with tab_screener:
    # ---------------------------------------------------------------------------
    # Sidebar controls
    # ---------------------------------------------------------------------------

    st.sidebar.header("⚙️ Screener Settings")

    universe_choice = st.sidebar.radio(
        "Universe",
        ["Nifty 50 (fast)", "Nifty 500 (full — slower)", "Custom list"],
        index=0,
    )

    if universe_choice == "Custom list":
        custom_input = st.sidebar.text_area(
            "Enter NSE symbols (comma-separated, no .NS suffix)",
            value="RELIANCE, TCS, INFY",
        )
        symbols_requested = [s.strip().upper() for s in custom_input.split(",") if s.strip()]
        # de-duplicate while preserving order, in case the user pastes repeats
        seen = set()
        symbols_requested = [s for s in symbols_requested if not (s in seen or seen.add(s))]
        universe_df = pd.DataFrame(
            {"Symbol": symbols_requested, "Company Name": symbols_requested, "Industry": "Unknown"}
        )
    else:
        index_key = "NIFTY50" if universe_choice.startswith("Nifty 50") else "NIFTY500"
        try:
            universe_df = load_universe(index_key)
        except Exception as e:
            st.sidebar.error(f"Failed to load universe list: {e}")
            st.stop()

    if universe_df.empty:
        st.sidebar.warning("Enter at least one valid NSE symbol above.")
        max_stocks = 0
    elif len(universe_df) <= 5:
        # Slider needs min < max; with a handful of symbols just use all of them, no slider needed.
        max_stocks = len(universe_df)
        st.sidebar.caption(f"Analyzing all {max_stocks} symbol(s) — too few for a range slider.")
    else:
        full_size = len(universe_df)
        # Default to the FULL selected universe — if someone picks "Nifty 500" they want 500,
        # not a silently truncated 50. The slider lets them deliberately scope down for speed,
        # but it never defaults to a fraction of what they asked for.
        max_stocks = st.sidebar.slider(
            "Max stocks to analyze this run",
            min_value=5,
            max_value=min(500, full_size),
            value=min(500, full_size),
            step=5,
            help="Defaults to the full universe you selected. A full Nifty 500 run can take "
            "15-40+ minutes on first fetch (no cache yet) due to yfinance rate limits. "
            "Drag down to scope to fewer stocks for a faster test run. "
            "Subsequent runs reuse the 6-hour disk cache and are much faster.",
        )
        if full_size > 100 and max_stocks == full_size:
            st.sidebar.info(
                f"⏱️ Running all {full_size} stocks can take a while on first fetch. "
                "Drag the slider down if you just want to test with fewer stocks first."
            )

    sector_filter = st.sidebar.multiselect(
        "Filter by Industry (optional)",
        sorted(universe_df["Industry"].dropna().unique().tolist())
        if "Industry" in universe_df.columns
        else [],
    )

    use_cache = st.sidebar.checkbox("Use cached data (6hr TTL)", value=True)

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Universe loaded: **{len(universe_df)}** symbols")

    # ---------------------------------------------------------------------------
    # Apply filters
    # ---------------------------------------------------------------------------

    filtered_df = universe_df.copy()
    if sector_filter:
        filtered_df = filtered_df[filtered_df["Industry"].isin(sector_filter)]

    filtered_df = filtered_df.head(max_stocks)
    selected_symbols = filtered_df["Symbol"].tolist()

    st.write(f"**{len(selected_symbols)} stocks** selected for analysis.")

    run = st.button("🚀 Run Deep Fundamental Analysis", type="primary")

    # ---------------------------------------------------------------------------
    # Run analysis
    # ---------------------------------------------------------------------------

    if run:
        if not selected_symbols:
            st.warning("No symbols selected.")
            st.stop()

        progress_bar = st.progress(0, text="Starting...")
        status_text = st.empty()

        def _progress(done, total, symbol):
            progress_bar.progress(done / total, text=f"Fetching {symbol} ({done}/{total})")

        source = YFinanceSource()
        fetch_results = fetch_universe(
            selected_symbols, source=source, progress_callback=_progress, use_cache=use_cache
        )

        progress_bar.progress(1.0, text="Fetch complete. Running analysis...")

        rows = []
        failures = []
        deep_data = {}  # symbol -> dict of everything needed for deep-dive / peer comparison later

        for symbol in selected_symbols:
            fr = fetch_results[symbol]
            if not fr.ok:
                failures.append((symbol, fr.error))
                continue

            analysis = analyze_stock(
                symbol, fr
            )  # sector medians filled in during the second pass below
            if analysis is None:
                failures.append((symbol, "Analysis failed unexpectedly after a successful fetch"))
                continue

            rows.append(analysis["row"])
            deep_data[symbol] = analysis["deep"]

        if not rows:
            st.error(
                "No data could be fetched for any selected symbol. Check network/rate limits and try again."
            )
            if failures:
                with st.expander("See failure details"):
                    st.write(pd.DataFrame(failures, columns=["Symbol", "Error"]))
            st.stop()

        df = pd.DataFrame(rows)

        # Second pass: now that we have the full df, compute proper sector-relative valuation & re-blend
        sector_medians_lookup_pe = df.groupby("Sector")["PE"].median()
        sector_medians_lookup_pb = df.groupby("Sector")["PB"].median()

        row_patches = {}
        for symbol in df["Symbol"]:
            d = deep_data[symbol]
            sector = d["info"].get("sector")
            med_pe = sector_medians_lookup_pe.get(sector)
            med_pb = sector_medians_lookup_pb.get(sector)
            row_patches[symbol] = refine_with_sector_context(symbol, d, med_pe, med_pb)

        # Apply each patch's fields back onto the df (same fields refine_with_sector_context returns)
        for col in [
            "Score",
            "Rating",
            "Blended Fair Value",
            "Est. Upside %",
            "Valuation Pillar",
            "Profitability Pillar",
            "Stability Pillar",
            "Growth Pillar",
            "Upside Pillar",
            "Strengths",
        ]:
            df[col] = df["Symbol"].map(lambda s: row_patches[s].get(col))

        df = attach_peer_context(df)
        df = df.sort_values("Score", ascending=False).reset_index(drop=True)

        st.session_state["screener_df"] = df
        st.session_state["deep_data"] = deep_data
        st.session_state["failures"] = failures
        st.session_state["universe_label"] = universe_choice  # snapshot at run-time, not read-time

    # ---------------------------------------------------------------------------
    # Display results (persisted across reruns via session_state)
    # ---------------------------------------------------------------------------

    if "screener_df" in st.session_state:
        df = st.session_state["screener_df"]
        deep_data = st.session_state["deep_data"]
        failures = st.session_state["failures"]
        result_universe_label = st.session_state.get("universe_label", universe_choice)

        st.divider()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Stocks Analyzed", len(df))
        c2.metric("Best Score", int(df["Score"].max()) if not df.empty else "—")
        c3.metric("Avg Score", round(df["Score"].mean(), 1) if not df.empty else "—")
        c4.metric("Failed Fetches", len(failures))

        if failures:
            with st.expander(f"⚠️ {len(failures)} symbols failed to fetch"):
                st.dataframe(
                    pd.DataFrame(failures, columns=["Symbol", "Error"]), use_container_width=True
                )

        st.divider()
        st.subheader("🏆 Fundamental Ranking")

        display_cols = [
            "Symbol",
            "Company",
            "Sector",
            "Score",
            "Rating",
            "Price",
            "PE",
            "PB",
            "ROE %",
            "Debt/Equity",
            "Profit Margin %",
            "Revenue CAGR %",
            "Net Income CAGR %",
            "Margin Trend",
            "Blended Fair Value",
            "Est. Upside %",
            "Strengths",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        st.dataframe(
            df[display_cols],
            use_container_width=True,
            height=500,
            column_config={
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
                "Est. Upside %": st.column_config.NumberColumn("Est. Upside %", format="%.1f%%"),
            },
        )

        csv = df.to_csv(index=False).encode("utf-8")

        export_payload = build_export_payload(df, deep_data, universe_label=result_universe_label)
        import json as _json

        json_bytes = _json.dumps(export_payload, indent=2, ensure_ascii=False).encode("utf-8")

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                "⬇ Download Full Report (CSV)", csv, "fundamental_pro_analysis.csv", "text/csv"
            )
        with dl_col2:
            st.download_button(
                "⬇ Download JSON (for external sites/APIs)",
                json_bytes,
                "latest.json",
                "application/json",
                help="Structured JSON feed designed for an external technical-analysis site to "
                "consume — see README 'Exporting for external consumption' for the schema "
                "and integration code.",
            )

        with st.expander("🔌 How to feed this into another website (techno-fundamental combo)"):
            st.markdown(
                """
    **Recommended approach: commit this JSON to a GitHub repo, fetch it from your other site.**

    1. Download the JSON above (or run `python scripts/export_daily.py` from the repo on a schedule).
    2. Commit it to a public (or private+token) GitHub repo, e.g. at `data/latest.json`.
    3. Your other site fetches the **raw file URL** directly over HTTPS — no API server needed:
       ```
       https://raw.githubusercontent.com/<you>/<repo>/main/data/latest.json
       ```
    4. Parse the JSON and join on `symbol` against your technical-analysis scores.

    This gives you a daily-refreshed, zero-infrastructure data feed. See the README section
    **"Exporting for external consumption"** for the full schema reference and example fetch
    code in Python, PHP, and JavaScript.
                """
            )

        st.divider()

        # -----------------------------------------------------------------
        # Sector overview
        # -----------------------------------------------------------------
        st.subheader("🏭 Sector Comparison")
        sector_medians = compute_sector_medians(df.rename(columns={"Sector": "Sector"}))
        if not sector_medians.empty:
            st.dataframe(sector_medians.round(2), use_container_width=True)
        else:
            st.caption("Not enough sector data to compute medians.")

        st.divider()

        # -----------------------------------------------------------------
        # Deep dive selector
        # -----------------------------------------------------------------
        st.subheader("🔍 Stock Deep Dive")
        selected_stock = st.selectbox("Select a stock for full breakdown", df["Symbol"].tolist())

        if selected_stock:
            d = deep_data[selected_stock]
            info = d["info"]
            result = d["result"]
            trends = d["trends"]
            dcf = d["dcf"]
            graham = d["graham"]
            relative = d.get("relative", {})
            blended = d.get("blended", {})

            st.markdown(f"### {info.get('longName', selected_stock)} ({selected_stock})")
            st.caption(f"{info.get('sector', 'Unknown')} | {info.get('industry', 'Unknown')}")

            pillar_cols = st.columns(5)
            pillars = result["pillar_scores"]
            for col, (name, val) in zip(pillar_cols, pillars.items(), strict=False):
                max_val = {
                    "Valuation": 20,
                    "Profitability": 20,
                    "Stability": 20,
                    "Growth": 25,
                    "Valuation Upside": 15,
                }[name]
                col.metric(name, f"{val}/{max_val}")

            st.markdown(f"**Overall Score: {result['total_score']}/100 — {result['rating']}**")

            with st.expander("📌 Score notes / key strengths & weaknesses"):
                for n in result["notes"]:
                    st.write(f"- {n}")

            st.markdown("#### 📈 Multi-Year Trend")
            tcol1, tcol2 = st.columns(2)
            with tcol1:
                if trends.get("revenue_series") and any(
                    v is not None for v in trends["revenue_series"]
                ):
                    st.caption("Revenue (Cr, oldest → newest)")
                    st.line_chart(pd.Series([v for v in trends["revenue_series"] if v is not None]))
                else:
                    st.caption("Revenue trend data unavailable.")
            with tcol2:
                if trends.get("net_income_series") and any(
                    v is not None for v in trends["net_income_series"]
                ):
                    st.caption("Net Income (Cr, oldest → newest)")
                    st.line_chart(
                        pd.Series([v for v in trends["net_income_series"] if v is not None])
                    )
                else:
                    st.caption("Net income trend data unavailable.")

            st.markdown("#### 💰 Intrinsic Value Estimates")
            vcol1, vcol2, vcol3, vcol4 = st.columns(4)
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            vcol1.metric("Current Price", f"₹{current_price:.2f}" if current_price else "—")

            if dcf.get("fair_value_per_share"):
                vcol2.metric(
                    "DCF Fair Value",
                    f"₹{dcf['fair_value_per_share']:.2f}",
                    f"{dcf.get('upside_pct', 0):.1f}%"
                    if dcf.get("upside_pct") is not None
                    else None,
                )
                if dcf.get("warning"):
                    vcol2.caption(f"⚠️ {dcf['warning']}")
            else:
                vcol2.metric("DCF Fair Value", "N/A")
                if dcf.get("warning"):
                    vcol2.caption(dcf["warning"])

            if graham.get("graham_value"):
                vcol3.metric(
                    "Graham Number",
                    f"₹{graham['graham_value']:.2f}",
                    f"{graham.get('upside_pct', 0):.1f}%"
                    if graham.get("upside_pct") is not None
                    else None,
                )
            else:
                vcol3.metric("Graham Number", "N/A")
                if graham.get("warning"):
                    vcol3.caption(graham["warning"])

            if blended.get("blended_value"):
                vcol4.metric(
                    "Blended Fair Value",
                    f"₹{blended['blended_value']:.2f}",
                    f"{blended.get('upside_pct', 0):.1f}%"
                    if blended.get("upside_pct") is not None
                    else None,
                )
                vcol4.caption(
                    f"Based on {blended['models_used']} model(s), range ₹{blended['low']:.2f}–₹{blended['high']:.2f}"
                )
            else:
                vcol4.metric("Blended Fair Value", "N/A")

            st.caption(
                "⚠️ These are rough model-based estimates from limited public data — treat as a starting "
                "point for further research, not a price target."
            )

            st.markdown("#### 🏭 Peer / Sector Context")
            pcol1, pcol2 = st.columns(2)
            med_pe = get_sector_median(df, info.get("sector"), "PE")
            med_roe = get_sector_median(df, info.get("sector"), "ROE %")
            with pcol1:
                st.write(
                    f"**Sector median PE:** {med_pe:.1f}" if med_pe else "Sector median PE: N/A"
                )
                st.write(f"**This stock's PE:** {info.get('trailingPE', 'N/A')}")
            with pcol2:
                st.write(
                    f"**Sector median ROE:** {med_roe:.1f}%"
                    if med_roe
                    else "Sector median ROE: N/A"
                )
                st.write(
                    f"**This stock's ROE:** {round(safe(info.get('returnOnEquity')) * 100, 1)}%"
                )

    else:
        st.info(
            "Configure settings in the sidebar and click **Run Deep Fundamental Analysis** to begin."
        )
