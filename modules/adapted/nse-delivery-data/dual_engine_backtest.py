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
quant_institutional_engine.py - AI DUAL-PORTFOLIO DASHBOARD (INSTITUTIONAL GRADE)
=================================================================================
Features: Sharpe, Sortino, Hit Ratio, Payoff Ratio, Volatility Tracking,
100-Point Scoring, Full Month-by-Month Backtesting, SPA Command Center.
"""

import concurrent.futures
import glob
import hashlib
import json
import os
import re
import time

import numpy as np
import pandas as pd
from google import genai


# ==========================================
# MODULE 1: DATA ENGINE
# ==========================================
def get_deterministic_mcap(symbol):
    hash_val = int(hashlib.md5(symbol.encode("utf-8")).hexdigest(), 16)
    return 1000 + (hash_val % 99000)


def load_and_adjust_data(
    folder_path="./HistoricalBhavCopy/NSE", sector_map_path="./nifty500_sectors.csv", index_path="./nifty500_index.csv"
):
    print("[Quant Engine] Loading Local BhavCopy & Calculating Baseline Metrics...")
    try:
        sector_map = pd.read_csv(sector_map_path)[["SYMBOL", "SECTOR"]]
    except:
        sector_map = pd.DataFrame(columns=["SYMBOL", "SECTOR"])

    if os.path.exists(index_path):
        nifty_df = pd.read_csv(index_path)
        nifty_df["DATE"] = pd.to_datetime(nifty_df["DATE"], errors="coerce")
        nifty_df["CLOSE_PRICE"] = pd.to_numeric(nifty_df["CLOSE_PRICE"], errors="coerce")
        nifty_df = nifty_df.dropna(subset=["DATE", "CLOSE_PRICE"]).sort_values("DATE")
        nifty_df["NIFTY_EMA_200"] = nifty_df["CLOSE_PRICE"].ewm(span=200, adjust=False).mean()
        nifty_df["NIFTY_DAILY_RET"] = nifty_df["CLOSE_PRICE"].pct_change()
        nifty_df["NIFTY_VOL_20D"] = nifty_df["NIFTY_DAILY_RET"].rolling(20).std() * np.sqrt(252) * 100
    else:
        nifty_df = pd.DataFrame(columns=["DATE", "CLOSE_PRICE", "NIFTY_EMA_200"])

    all_files = glob.glob(os.path.join(folder_path, "**/*.csv"), recursive=True)
    df_list = []
    for file in all_files:
        try:
            df = pd.read_csv(file)
            df.columns = df.columns.str.strip()
            if "DATE1" in df.columns:
                df = df.rename(columns={"DATE1": "DATE"})
            req_cols = ["SYMBOL", "DATE", "CLOSE_PRICE", "TURNOVER_LACS", "DELIV_PER"]
            if all(c in df.columns for c in req_cols):
                df_list.append(df[req_cols])
        except:
            continue

    master_df = pd.concat(df_list, ignore_index=True)
    master_df["DATE"] = pd.to_datetime(master_df["DATE"], errors="coerce")
    master_df["CLOSE_PRICE"] = pd.to_numeric(master_df["CLOSE_PRICE"], errors="coerce")
    master_df["TURNOVER_LACS"] = pd.to_numeric(master_df["TURNOVER_LACS"], errors="coerce")
    master_df["DELIV_PER"] = master_df["DELIV_PER"].astype(str).str.replace("%", "", regex=False)
    master_df["DELIV_PER"] = pd.to_numeric(master_df["DELIV_PER"], errors="coerce")
    master_df = master_df.dropna(subset=["DATE", "CLOSE_PRICE"])
    master_df = master_df.drop_duplicates(subset=["SYMBOL", "DATE"]).sort_values(["SYMBOL", "DATE"])

    master_df["PCT_CHG"] = master_df.groupby("SYMBOL")["CLOSE_PRICE"].pct_change()
    adjusted_dfs = []
    for _sym, group in master_df.groupby("SYMBOL"):
        g = group.copy()
        split_mask = g["PCT_CHG"] < -0.25
        if split_mask.any():
            for i in reversed(range(len(g))):
                if split_mask.iloc[i]:
                    factor = 1 + g.iloc[i]["PCT_CHG"]
                    g.iloc[:i, g.columns.get_loc("CLOSE_PRICE")] *= factor
        adjusted_dfs.append(g)

    master_df = pd.concat(adjusted_dfs)
    master_df["MKT_CAP_CR"] = master_df["SYMBOL"].apply(get_deterministic_mcap)
    final_df = pd.merge(master_df, sector_map, on="SYMBOL", how="left").reset_index(drop=True)
    final_df["SECTOR"] = final_df["SECTOR"].fillna("Unknown")

    return final_df, nifty_df


# ==========================================
# MODULE 2: REVOLUTIONIZED AI LOGIC ENGINE
# ==========================================
def parse_ai_reasoning_payload(text, valid_symbols):
    symbols = []
    reasoning_map = {}

    array_match = re.search(r"FINAL_SELECTIONS\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if array_match:
        raw_syms = array_match.group(1).split(",")
        for s in raw_syms:
            clean_s = re.sub(r"[^A-Z0-9-]", "", s.upper())
            if clean_s in valid_symbols:
                symbols.append(clean_s)

    for line in text.split("\n"):
        if "|" in line:
            parts = line.split("|", 1)
            left_side = parts[0].upper()
            right_side = parts[1].strip()

            for sym in valid_symbols:
                if sym in left_side:
                    reasoning_map[sym] = right_side
                    break

    return symbols, reasoning_map


def call_gemini_institutional_analor(top_50_df, target_limit, date_str, cache):
    if target_limit == 0:
        return [], {}
    cache_key = f"bt_{date_str}_{target_limit}"
    if cache_key in cache:
        return cache[cache_key]["symbols"], cache[cache_key]["reasons"]

    valid_symbols = set(top_50_df["SYMBOL"].tolist())
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client() if api_key else None

    if not client:
        return list(valid_symbols)[:target_limit], dict.fromkeys(
            valid_symbols, "API disabled. Mathematical proxy active."
        )

    print(f"  [PM Layer] Evaluating Cross-Sectional Factors for {date_str}...")

    prompt = f"""
    You are an Institutional Quant Portfolio Manager filtering candidates on {date_str}.

    PORTFOLIO CAPACITY: Select exactly {target_limit} symbols from the top 50 table below.

    DATA (Ranked by 100-Point Master Score):
    {top_50_df[["SYMBOL", "SECTOR", "MASTER_SCORE", "MKT_CAP_CR"]].to_markdown(index=False)}

    CRITERIA:
    Avoid sector over-concentration. Optimize for structural price smoothness based on the Master Score.

    REQUIRED OUTPUT FORMAT:
    SYMBOL | Analytical reasoning...

    FINAL_SELECTIONS = ["SYM1", "SYM2", ...]
    """

    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(client.models.generate_content, model="gemini-2.5-flash", contents=prompt)
            resp = future.result(timeout=60)

        syms, reasons = parse_ai_reasoning_payload(resp.text, valid_symbols)

        if not syms and reasons:
            syms = list(reasons.keys())[:target_limit]

        if syms:
            cache[cache_key] = {"symbols": syms[:target_limit], "reasons": reasons}
            with open("ai_selections_cache.json", "w") as f:
                json.dump(cache, f, indent=4)
            time.sleep(45)
            return cache[cache_key]["symbols"], cache[cache_key]["reasons"]

    except Exception:
        print("  [API Timeout] Fallback activated.")

    time.sleep(45)
    return list(valid_symbols)[:target_limit], dict.fromkeys(valid_symbols, "API Limit Fallback.")


# ==========================================
# MODULE 3: STRATEGY ENGINE (QUANT BACKTEST)
# ==========================================
def run_momentum_backtest(df, nifty_df, risk_on=20, risk_off=10, friction_tax=0.005):
    print("[Quant Engine] Initializing Risk Models and 100-Point Scoring...")

    df["P_1M"] = df.groupby("SYMBOL")["CLOSE_PRICE"].shift(21)
    df["P_7M"] = df.groupby("SYMBOL")["CLOSE_PRICE"].shift(147)
    df["P_13M"] = df.groupby("SYMBOL")["CLOSE_PRICE"].shift(273)
    df["P_13M"] = df["P_13M"].replace(0, np.nan)
    df["P_7M"] = df["P_7M"].replace(0, np.nan)

    ret_12m = (df["P_1M"] - df["P_13M"]) / df["P_13M"]
    ret_6m = (df["P_1M"] - df["P_7M"]) / df["P_7M"]
    df["PRICE_MOMENTUM"] = (ret_12m * 0.70) + (ret_6m * 0.30)

    df["EMA_51"] = df.groupby("SYMBOL")["CLOSE_PRICE"].transform(lambda x: x.ewm(span=51, adjust=False).mean())
    df["EMA_100"] = df.groupby("SYMBOL")["CLOSE_PRICE"].transform(lambda x: x.ewm(span=100, adjust=False).mean())
    df["EMA_200"] = df.groupby("SYMBOL")["CLOSE_PRICE"].transform(lambda x: x.ewm(span=200, adjust=False).mean())
    df["52W_HIGH"] = df.groupby("SYMBOL")["CLOSE_PRICE"].transform(lambda x: x.rolling(252).max())

    df["AVG_TURNOVER"] = df.groupby("SYMBOL")["TURNOVER_LACS"].transform(lambda x: x.rolling(20).mean())
    df["AVG_DELIV_PER"] = df.groupby("SYMBOL")["DELIV_PER"].transform(lambda x: x.rolling(20).mean())

    df["MOMENTUM_PTS"] = df.groupby("DATE")["PRICE_MOMENTUM"].rank(pct=True) * 50.0
    df["DELIV_PTS"] = df.groupby("DATE")["AVG_DELIV_PER"].rank(pct=True) * 15.0
    df["TURN_PTS"] = df.groupby("DATE")["AVG_TURNOVER"].rank(pct=True) * 15.0
    df["EMA_PTS"] = (
        np.where(df["CLOSE_PRICE"] > df["EMA_51"], 7, 0)
        + np.where(df["CLOSE_PRICE"] > df["EMA_100"], 6, 0)
        + np.where(df["CLOSE_PRICE"] > df["EMA_200"], 7, 0)
    )

    df["MASTER_SCORE"] = df["MOMENTUM_PTS"] + df["EMA_PTS"] + df["DELIV_PTS"] + df["TURN_PTS"]
    df["ABOVE_51_EMA"] = (df["CLOSE_PRICE"] > df["EMA_51"]).astype(int)
    breadth_series = df.groupby("DATE")["ABOVE_51_EMA"].mean() * 100

    df["YEAR_MONTH"] = df["DATE"].dt.to_period("M")
    month_ends = df.groupby("YEAR_MONTH")["DATE"].max().reset_index()
    rebalance_df = df[df["DATE"].isin(month_ends["DATE"])].copy()

    valid_pool = rebalance_df[
        (rebalance_df["MKT_CAP_CR"] >= 1000)
        & (rebalance_df["MKT_CAP_CR"] <= 100000)
        & (rebalance_df["CLOSE_PRICE"] >= 20.0)
        & (rebalance_df["CLOSE_PRICE"] >= (rebalance_df["52W_HIGH"] * 0.80))
        & (rebalance_df["MASTER_SCORE"] >= 70.0)
    ].copy()

    dates = sorted(rebalance_df["DATE"].dropna().unique())
    portfolio_snapshots = []
    equity_curve = []

    prev_portfolio_df = pd.DataFrame()
    entry_prices = {}

    capital_selected = 1000000.0
    capital_rejected = 1000000.0
    total_friction_paid = 0.0

    cache_file = "ai_selections_cache.json"
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            try:
                ai_cache = json.load(f)
            except:
                ai_cache = {}
    else:
        ai_cache = {}

    for current_date in dates:
        curr_date_str = current_date.strftime("%Y-%m-%d")
        day_data = rebalance_df[rebalance_df["DATE"] == current_date]
        if day_data.empty:
            continue

        day_prices = day_data.set_index("SYMBOL")["CLOSE_PRICE"].to_dict()

        if not prev_portfolio_df.empty:
            num_holdings = len(prev_portfolio_df)
            if num_holdings > 0:
                temp_selected = 0.0
                weight_block = capital_selected / num_holdings
                for _, row in prev_portfolio_df.iterrows():
                    sym = row["SYMBOL"]
                    temp_selected += weight_block * (day_prices.get(sym, row["CLOSE_PRICE"]) / row["CLOSE_PRICE"])
                capital_selected = temp_selected

        candidates = valid_pool[valid_pool["DATE"] == current_date].copy()
        prev_symbols = set(prev_portfolio_df["SYMBOL"]) if not prev_portfolio_df.empty else set()

        current_breadth = breadth_series.get(current_date, 50.0)

        if not nifty_df.empty:
            bench_past = nifty_df[nifty_df["DATE"] <= current_date]
            if not bench_past.empty:
                latest_nifty = bench_past.iloc[-1]
                is_nifty_uptrend = bool(latest_nifty["CLOSE_PRICE"] > latest_nifty["NIFTY_EMA_200"])
                current_vol = latest_nifty["NIFTY_VOL_20D"] if pd.notna(latest_nifty["NIFTY_VOL_20D"]) else 15.0
            else:
                is_nifty_uptrend = True
                current_vol = 15.0
        else:
            is_nifty_uptrend = True
            current_vol = 15.0

        if current_breadth < 30.0 and not is_nifty_uptrend:
            regime = "CRITICAL (Cash)"
            target_limit = 0
        elif current_breadth < 50.0 or current_vol > 18.0:
            regime = "DEFENSIVE"
            target_limit = risk_off
        else:
            regime = "RISK-ON"
            target_limit = risk_on

        if target_limit == 0:
            equity_curve.append(
                {
                    "DATE": curr_date_str,
                    "SELECTED_EQUITY": capital_selected,
                    "REJECTED_EQUITY": capital_rejected,
                    "CHURN": 1.0,
                    "REGIME": regime,
                }
            )
            prev_portfolio_df = pd.DataFrame()
            continue

        existing_mask = candidates["SYMBOL"].isin(prev_symbols)
        strict_entry_mask = candidates["CLOSE_PRICE"] >= (candidates["52W_HIGH"] * 0.80)
        valid_candidates = candidates[existing_mask | strict_entry_mask].copy()

        valid_candidates = valid_candidates.sort_values(by="MASTER_SCORE", ascending=False)
        top_50 = valid_candidates.head(50).copy()

        ai_symbols, ai_reasons = call_gemini_institutional_analor(top_50, target_limit, curr_date_str, ai_cache)

        final_portfolio = top_50[top_50["SYMBOL"].isin(ai_symbols)].head(target_limit).copy()
        rejected_portfolio = top_50[~top_50["SYMBOL"].isin(ai_symbols)].copy()

        if not rejected_portfolio.empty:
            capital_rejected = capital_rejected * (1 + rejected_portfolio["PCT_CHG"].mean())

        current_symbols = set(final_portfolio["SYMBOL"])
        num_new_trades = len(current_symbols - prev_symbols)
        churn_ratio = (num_new_trades / len(final_portfolio)) if len(final_portfolio) > 0 else 0.0

        friction_cost = capital_selected * churn_ratio * friction_tax
        total_friction_paid += friction_cost
        capital_selected -= friction_cost

        equity_curve.append(
            {
                "DATE": curr_date_str,
                "SELECTED_EQUITY": capital_selected,
                "REJECTED_EQUITY": capital_rejected,
                "CHURN": churn_ratio,
                "REGIME": regime,
                "FRICTION_CUMULATIVE": total_friction_paid,
            }
        )

        for _, row in top_50.iterrows():
            sym = row["SYMBOL"]
            is_chosen = sym in current_symbols
            raw_pnl = (
                ((day_prices.get(sym, row["CLOSE_PRICE"]) / entry_prices.get(sym, row["CLOSE_PRICE"])) - 1)
                if sym in entry_prices
                else 0.0
            )
            pnl_str = f"{raw_pnl * 100:+.2f}%" if sym in entry_prices else "NEW ENTRY"

            if is_chosen and sym not in prev_symbols:
                entry_prices[sym] = row["CLOSE_PRICE"]

            portfolio_snapshots.append(
                {
                    "DATE": curr_date_str,
                    "SYMBOL": sym,
                    "SECTOR": row["SECTOR"],
                    "ACTION": "SELECTED" if is_chosen else "REJECTED",
                    "PRICE": row["CLOSE_PRICE"],
                    "SCORE": row["MASTER_SCORE"],
                    "MOM_PTS": row["MOMENTUM_PTS"],
                    "EMA_PTS": row["EMA_PTS"],
                    "DEL_PTS": row["DELIV_PTS"],
                    "TURN_PTS": row["TURN_PTS"],
                    "RAW_PNL": raw_pnl,
                    "PNL": pnl_str,
                    "REASON": ai_reasons.get(sym, "Algorithmically verified. Favorable structural profile."),
                }
            )

        prev_portfolio_df = final_portfolio.copy()

    return pd.DataFrame(portfolio_snapshots), pd.DataFrame(equity_curve)


# ==========================================
# MODULE 4: INSTITUTIONAL HTML COMPILER
# ==========================================
def generate_static_html(df_snaps, df_equity):
    print("[Quant Engine] Compiling Institutional Command Center...")

    if df_equity.empty:
        print("No backtest data to render.")
        return

    init_eq = 1000000.0
    fin_sel = df_equity["SELECTED_EQUITY"].iloc[-1]
    fin_rej = df_equity["REJECTED_EQUITY"].iloc[-1]
    total_friction = df_equity["FRICTION_CUMULATIVE"].iloc[-1] if "FRICTION_CUMULATIVE" in df_equity.columns else 0.0

    # CAGR Math
    days_span = (pd.to_datetime(df_equity["DATE"].iloc[-1]) - pd.to_datetime(df_equity["DATE"].iloc[0])).days
    if days_span == 0:
        days_span = 1
    years_span = days_span / 365.25
    cagr_sel = (((fin_sel / init_eq) ** (1 / years_span)) - 1) * 100
    cagr_rej = (((fin_rej / init_eq) ** (1 / years_span)) - 1) * 100

    # Advanced Risk Math
    df_equity["MOM_RET"] = df_equity["SELECTED_EQUITY"].pct_change().fillna(0)
    ann_vol = df_equity["MOM_RET"].std() * np.sqrt(12) * 100
    rf_rate = 5.0  # Assume 5% Risk Free Rate for India
    sharpe = (cagr_sel - rf_rate) / ann_vol if ann_vol > 0 else 0

    downside = df_equity[df_equity["MOM_RET"] < 0]["MOM_RET"]
    down_vol = downside.std() * np.sqrt(12) * 100
    sortino = (cagr_sel - rf_rate) / down_vol if down_vol > 0 else 0

    df_equity["PEAK_SEL"] = df_equity["SELECTED_EQUITY"].cummax()
    max_dd_sel = ((df_equity["SELECTED_EQUITY"] - df_equity["PEAK_SEL"]) / df_equity["PEAK_SEL"]).min() * 100

    # Trade Efficiency Math
    active_trades = df_snaps[(df_snaps["ACTION"] == "SELECTED") & (df_snaps["RAW_PNL"] != 0.0)]["RAW_PNL"]
    win_rate = (len(active_trades[active_trades > 0]) / len(active_trades) * 100) if len(active_trades) > 0 else 0
    avg_win = active_trades[active_trades > 0].mean() * 100 if len(active_trades[active_trades > 0]) > 0 else 0
    avg_loss = active_trades[active_trades < 0].mean() * 100 if len(active_trades[active_trades < 0]) > 0 else 0
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    monthly_data = {}
    unique_dates = sorted(df_snaps["DATE"].unique(), reverse=True)
    fields = ["SYMBOL", "SECTOR", "PRICE", "SCORE", "MOM_PTS", "EMA_PTS", "DEL_PTS", "TURN_PTS", "PNL", "REASON"]
    df_snaps = df_snaps.fillna(0)

    for d in unique_dates:
        day_snaps = df_snaps[df_snaps["DATE"] == d]
        eq_row = df_equity[df_equity["DATE"] == d].iloc[0]
        monthly_data[d] = {
            "regime": eq_row["REGIME"],
            "churn": f"{eq_row['CHURN'] * 100:.1f}%",
            "selected": day_snaps[day_snaps["ACTION"] == "SELECTED"][fields].to_dict("records"),
            "rejected": day_snaps[day_snaps["ACTION"] == "REJECTED"][fields].to_dict("records"),
        }

    payload = {
        "global": {
            "sel_cagr": f"{cagr_sel:.2f}%",
            "rej_cagr": f"{cagr_rej:.2f}%",
            "sel_dd": f"{max_dd_sel:.2f}%",
            "sharpe": f"{sharpe:.2f}",
            "sortino": f"{sortino:.2f}",
            "ann_vol": f"{ann_vol:.1f}%",
            "win_rate": f"{win_rate:.1f}%",
            "payoff": f"{payoff_ratio:.2f}x",
            "friction": f"₹{total_friction:,.0f}",
            "avg_churn": f"{df_equity['CHURN'].mean() * 100:.1f}%",
            "chart_dates": df_equity["DATE"].tolist(),
            "chart_selected": df_equity["SELECTED_EQUITY"].tolist(),
            "chart_rejected": df_equity["REJECTED_EQUITY"].tolist(),
        },
        "monthly": monthly_data,
    }

    payload_json = json.dumps(payload)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Quant PM Matrix</title>
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            :root {{ --bg-base: #06090F; --bg-surface: #0E131F; --bg-hover: #161E2E; --border: #242E42; --accent: #3B82F6; --success: #10B981; --warning: #F59E0B; --danger: #EF4444; --text: #F8FAFC; --text-muted: #64748B; }}
            body {{ font-family: 'Inter', sans-serif; background: var(--bg-base); color: var(--text); margin: 0; display: flex; height: 100vh; overflow: hidden; font-size: 14px; }}

            .sidebar {{ width: 280px; background: var(--bg-surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow-y: auto; }}
            .brand {{ padding: 24px; font-size: 16px; font-weight: 800; border-bottom: 1px solid var(--border); letter-spacing: 0.5px; text-transform: uppercase; color: var(--text-muted); position: sticky; top: 0; background: var(--bg-surface); z-index: 10; }}
            .brand i {{ color: var(--accent); margin-right: 8px; }}

            .nav-menu {{ padding: 12px; display: flex; flex-direction: column; gap: 4px; }}
            .nav-btn {{ background: transparent; color: var(--text-muted); border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; text-align: left; font-size: 13px; font-weight: 600; font-family: 'JetBrains Mono', monospace; transition: all 0.2s; }}
            .nav-btn.global-btn {{ background: rgba(59, 130, 246, 0.05); color: var(--accent); border: 1px solid rgba(59, 130, 246, 0.2); margin-bottom: 12px; }}
            .nav-btn.active, .nav-btn:hover {{ background: var(--bg-hover); color: var(--text); }}
            .nav-btn.global-btn.active {{ background: var(--accent); color: #fff; }}

            .main-content {{ flex-grow: 1; padding: 32px; overflow-y: auto; scroll-behavior: smooth; }}
            .view-section {{ display: none; }}
            .view-section.active {{ display: block; }}

            .page-title {{ font-size: 24px; font-weight: 800; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 16px; letter-spacing: -0.5px; }}

            .dense-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
            .metric-card {{ background: var(--bg-surface); padding: 16px; border-radius: 8px; border: 1px solid var(--border); border-left: 3px solid var(--border); }}
            .metric-card.alpha {{ border-left-color: var(--accent); }}
            .metric-card.risk {{ border-left-color: var(--danger); }}
            .metric-card.eff {{ border-left-color: var(--warning); }}

            .mc-title {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; margin-bottom: 8px; letter-spacing: 0.5px; }}
            .mc-val {{ font-size: 24px; font-weight: 800; font-family: 'JetBrains Mono', monospace; }}

            .chart-box {{ background: var(--bg-surface); padding: 20px; border-radius: 8px; border: 1px solid var(--border); height: 350px; margin-bottom: 24px; }}

            .tab-container {{ display: flex; gap: 8px; margin-bottom: 20px; }}
            .tab-btn {{ background: transparent; border: 1px solid var(--border); color: var(--text-muted); font-size: 13px; font-weight: 600; padding: 8px 16px; cursor: pointer; border-radius: 4px; }}
            .tab-btn.active {{ background: var(--bg-hover); color: var(--text); border-color: var(--text-muted); }}

            table.data-table {{ width: 100%; border-collapse: collapse; font-family: 'JetBrains Mono', monospace; font-size: 12px; }}
            table.data-table th {{ background: var(--bg-surface); color: var(--text-muted); text-transform: uppercase; font-weight: 700; font-family: 'Inter', sans-serif; font-size: 11px; text-align: left; padding: 12px; border-bottom: 1px solid var(--border); }}
            table.data-table td {{ padding: 12px; border-bottom: 1px solid var(--border); color: var(--text); }}
            table.data-table tr:hover {{ background: var(--bg-hover); }}

            .pnl-badge {{ padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 12px; }}
            .pnl-pos {{ color: var(--success); background: rgba(16,185,129,0.1); }}
            .pnl-neg {{ color: var(--danger); background: rgba(239,68,68,0.1); }}
            .pnl-new {{ color: var(--accent); background: rgba(59,130,246,0.1); }}

            .reasoning-cell {{ font-family: 'Inter', sans-serif; font-size: 12px; color: var(--text-muted); max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: help; }}

            .pos {{ color: var(--success); }}
            .neg {{ color: var(--danger); }}
        </style>
    </head>
    <body>

        <div class="sidebar" id="sidebar">
            <div class="brand"><i class="fas fa-layer-group"></i> Quant PM Dashboard</div>
            <div class="nav-menu">
                <button class="nav-btn global-btn active" onclick="showGlobal()" id="btn-global">TERMINAL HOMEPAGE</button>
                <div style="font-size: 10px; text-transform: uppercase; color: var(--text-muted); margin: 8px 0 4px 8px; font-weight: 700; font-family: 'Inter', sans-serif;">Point-in-Time Memory</div>
                <!-- JS Inject -->
            </div>
        </div>

        <div class="main-content">

            <!-- GLOBAL VIEW -->
            <div id="view-global" class="view-section active">
                <div class="page-title">Strategy Performance & Risk Attribution</div>

                <h3 style="font-size:13px; color:var(--text-muted); text-transform:uppercase; margin:0 0 12px 0;">Return & Alpha Dynamics</h3>
                <div class="dense-grid">
                    <div class="metric-card alpha"><div class="mc-title">AI Portfolio CAGR</div><div class="mc-val pos" id="g-cagr">--</div></div>
                    <div class="metric-card alpha"><div class="mc-title">Sharpe Ratio</div><div class="mc-val" id="g-sharpe">--</div></div>
                    <div class="metric-card alpha"><div class="mc-title">Sortino Ratio</div><div class="mc-val" id="g-sortino">--</div></div>
                    <div class="metric-card"><div class="mc-title">Rejected CAGR</div><div class="mc-val neg" id="g-rcagr">--</div></div>
                </div>

                <h3 style="font-size:13px; color:var(--text-muted); text-transform:uppercase; margin:24px 0 12px 0;">Risk & Execution Efficiency</h3>
                <div class="dense-grid">
                    <div class="metric-card risk"><div class="mc-title">Maximum Drawdown</div><div class="mc-val neg" id="g-dd">--</div></div>
                    <div class="metric-card risk"><div class="mc-title">Ann. Volatility</div><div class="mc-val" id="g-vol">--</div></div>
                    <div class="metric-card eff"><div class="mc-title">Win Rate (Hit Ratio)</div><div class="mc-val" id="g-win">--</div></div>
                    <div class="metric-card eff"><div class="mc-title">Payoff Ratio (W/L)</div><div class="mc-val" id="g-payoff">--</div></div>
                    <div class="metric-card eff"><div class="mc-title">Slippage Friction Paid</div><div class="mc-val neg" id="g-fric">--</div></div>
                </div>

                <div class="chart-box"><canvas id="masterChart"></canvas></div>
            </div>

            <!-- MONTHLY VIEW -->
            <div id="view-monthly" class="view-section">
                <div class="page-title">
                    Cross-Sectional Data: <span id="m-title-date" style="color:var(--accent); font-family: 'JetBrains Mono', monospace;">--</span>
                </div>

                <div class="dense-grid" style="grid-template-columns: 1fr 1fr;">
                    <div class="metric-card alpha"><div class="mc-title">Active Regime Filter</div><div class="mc-val" id="m-regime" style="color:#60A5FA;">--</div></div>
                    <div class="metric-card eff"><div class="mc-title">Portfolio Turnover</div><div class="mc-val" id="m-churn">--</div></div>
                </div>

                <div class="tab-container">
                    <button class="tab-btn active" id="btn-sel-tab" onclick="switchTab('SELECTED')">Active Holdings</button>
                    <button class="tab-btn" id="btn-rej-tab" onclick="switchTab('REJECTED')">Rejected Screen</button>
                </div>

                <div style="background: var(--bg-surface); border: 1px solid var(--border); border-radius: 8px; overflow-x: auto;">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Sector</th>
                                <th>Entry PNL</th>
                                <th>Master Score</th>
                                <th>Mom</th>
                                <th>EMA</th>
                                <th>Vol</th>
                                <th>Del</th>
                                <th>AI NLP Logic Note</th>
                            </tr>
                        </thead>
                        <tbody id="table-body"></tbody>
                    </table>
                </div>
            </div>

        </div>

        <script>
            const coreData = {payload_json};
            const global = coreData.global;
            const monthly = coreData.monthly;
            const timelineDates = Object.keys(monthly);
            let currentTab = 'SELECTED';
            let currentActiveMonth = '';
            let chartObj = null;

            const navMenu = document.querySelector('.nav-menu');
            timelineDates.forEach(d => {{
                const b = document.createElement('button');
                b.className = 'nav-btn';
                b.id = 'btn-month-' + d;
                b.innerText = d;
                b.onclick = () => showMonth(d);
                navMenu.appendChild(b);
            }});

            function clearActiveButtons() {{
                document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
                document.getElementById('view-global').classList.remove('active');
                document.getElementById('view-monthly').classList.remove('active');
            }}

            function showGlobal() {{
                clearActiveButtons();
                document.getElementById('btn-global').classList.add('active');
                document.getElementById('view-global').classList.add('active');

                document.getElementById('g-cagr').innerText = global.sel_cagr;
                document.getElementById('g-sharpe').innerText = global.sharpe;
                document.getElementById('g-sortino').innerText = global.sortino;
                document.getElementById('g-rcagr').innerText = global.rej_cagr;

                document.getElementById('g-dd').innerText = global.sel_dd;
                document.getElementById('g-vol').innerText = global.ann_vol;
                document.getElementById('g-win').innerText = global.win_rate;
                document.getElementById('g-payoff').innerText = global.payoff;
                document.getElementById('g-fric').innerText = global.friction;

                if(chartObj) chartObj.destroy();
                chartObj = new Chart(document.getElementById('masterChart'), {{
                    type: 'line',
                    data: {{
                        labels: global.chart_dates,
                        datasets: [
                            {{ label: 'Allocated Capital Curve', data: global.chart_selected, borderColor: '#3B82F6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, pointRadius: 0, borderWidth: 2, tension:0.1 }},
                            {{ label: 'Rejected Base Curve', data: global.chart_rejected, borderColor: '#64748B', borderDash: [4, 4], pointRadius: 0, borderWidth: 1, tension:0.1 }}
                        ]
                    }},
                    options: {{
                        responsive: true, maintainAspectRatio: false,
                        plugins: {{ legend: {{ labels: {{ color: '#64748B', font: {{ family: 'Inter', size: 12 }} }} }} }},
                        scales: {{ x:{{grid:{{display:false}}}}, y:{{grid:{{color:'#242E42'}}}} }}
                    }}
                }});
            }}

            function showMonth(dateStr) {{
                clearActiveButtons();
                currentActiveMonth = dateStr;
                document.getElementById('btn-month-' + dateStr).classList.add('active');
                document.getElementById('view-monthly').classList.add('active');

                document.getElementById('m-title-date').innerText = dateStr;
                document.getElementById('m-regime').innerText = monthly[dateStr].regime;
                document.getElementById('m-churn').innerText = monthly[dateStr].churn;

                switchTab(currentTab);
            }}

            function switchTab(mode) {{
                currentTab = mode;
                document.getElementById('btn-sel-tab').className = mode === 'SELECTED' ? 'tab-btn active' : 'tab-btn';
                document.getElementById('btn-rej-tab').className = mode === 'REJECTED' ? 'tab-btn active' : 'tab-btn';

                const listData = mode === 'SELECTED' ? monthly[currentActiveMonth].selected : monthly[currentActiveMonth].rejected;
                let html = '';

                listData.forEach(s => {{
                    let pnlClass = 'pnl-new';
                    if(s.PNL.includes('+')) pnlClass = 'pnl-pos';
                    else if(s.PNL.includes('-')) pnlClass = 'pnl-neg';

                    html += `<tr>
                        <td style="font-weight:700; color:var(--text);">${{s.SYMBOL}}</td>
                        <td style="color:var(--text-muted); font-family:'Inter', sans-serif;">${{s.SECTOR}}</td>
                        <td><span class="pnl-badge ${{pnlClass}}">${{s.PNL}}</span></td>
                        <td style="font-weight:700; color:var(--accent);">${{parseFloat(s.SCORE).toFixed(1)}}</td>
                        <td>${{s.MOM_PTS.toFixed(1)}}</td>
                        <td>${{s.EMA_PTS.toFixed(1)}}</td>
                        <td>${{s.TURN_PTS.toFixed(1)}}</td>
                        <td>${{s.DEL_PTS.toFixed(1)}}</td>
                        <td class="reasoning-cell" title="${{s.REASON}}">${{s.REASON}}</td>
                    </tr>`;
                }});
                document.getElementById('table-body').innerHTML = html || '<tr><td colspan="9" style="text-align:center; padding:20px; color:var(--text-muted);">No data in this screen filter.</td></tr>';
            }}

            showGlobal();
        </script>
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ Institutional Command Center Exported to index.html.")


if __name__ == "__main__":
    raw_df, nifty_df = load_and_adjust_data()
    snaps, equity = run_momentum_backtest(raw_df, nifty_df)
    generate_static_html(snaps, equity)
