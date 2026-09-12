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


import csv
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))
sys.path.append(base_dir)

from app.database import DatabaseManager

N_LONG = 7
N_SHORT = 7

# Maps CSV company names → NSE symbols
FUTURES_NAME_TO_NSE = {
    "Reliance Industries": "RELIANCE",
    "HDFC Bank": "HDFCBANK",
    "Bharti Airtel": "BHARTIARTL",
    "ICICI Bank": "ICICIBANK",
    "State Bank of India": "SBIN",
    "Tata Consultancy Services": "TCS",
    "Bajaj Finance": "BAJFINANCE",
    "Larsen & Toubro": "LT",
    "Hindustan Unilever": "HINDUNILVR",
    "LIC of India": "LICI",
    "Infosys": "INFY",
    "Sun Pharmaceutical": "SUNPHARMA",
    "Adani Power": "ADANIPOWER",
    "Adani Ports & SEZ": "ADANIPORTS",
    "Maruti Suzuki": "MARUTI",
    "Axis Bank": "AXISBANK",
    "Mahindra & Mahindra": "M&M",
    "Kotak Bank": "KOTAKBANK",
    "ITC": "ITC",
    "NTPC": "NTPC",
    "Oil & Natural Gas Corporation": "ONGC",
    "Titan": "TITAN",
    "Adani Enterprises": "ADANIENT",
    "UltraTech Cement": "ULTRACEMCO",
    "HCL Technologies": "HCLTECH",
    "JSW Steel": "JSWSTEEL",
    "Bharat Electronics": "BEL",
    "Bajaj Auto": "BAJAJ-AUTO",
    "Hindustan Aeronautics": "HAL",
    "Bajaj Finserv": "BAJAJFINSV",
    "Coal India": "COALINDIA",
    "Nestle": "NESTLEIND",
    "Power Grid Corporation of India": "POWERGRID",
    "Avenue Supermarts DMart": "DMART",
    "Hindustan Zinc": "HINDZINC",
    "Tata Steel": "TATASTEEL",
    "Asian Paints": "ASIANPAINT",
    "Hindalco Industries": "HINDALCO",
    "Eternal": "ETERNAL",
    "Adani Green Energy": "ADANIGREEN",
    "Shriram Finance": "SHRIRAMFIN",
    "Grasim Industries": "GRASIM",
    "Wipro": "WIPRO",
    "Indian Oil Corporation": "IOC",
    "Eicher Motors": "EICHERMOT",
    "SBI Life Insurance": "SBILIFE",
    "Divis Laboratories": "DIVISLAB",
    "Varun Beverages": "VBL",
    "Interglobe Aviation": "INDIGO",
    "BSE": "BSE",
    "Adani Energy Solutions": "ADANIENSOL",
    "Solar Industries": "SOLARINDS",
    "TVS Motors": "TVSMOTOR",
    "Hitachi Energy": "HITACHIENERGY",
    "Trent": "TRENT",
    "Torrent Pharmaceuticals": "TORNTPHARM",
    "Jio Financial Services": "JIOFIN",
    "Pidilite Industries": "PIDILITIND",
    "Hyundai Motor India": "HYUNDAI",
    "Vodafone Idea": "IDEA",
    "Cummins": "CUMMINSIND",
    "DLF": "DLF",
    "Samvardhana Motherson International": "MOTHERSON",
    "Bharat Heavy Electricals": "BHEL",
    "Power Finance Corporation": "PFC",
    "ABB": "ABB",
    "Polycab": "POLYCAB",
    "Tech Mahindra": "TECHM",
    "Bank of Baroda": "BANKBARODA",
    "CG Power & Industrial Solutions": "CGPOWER",
    "Siemens": "SIEMENS",
    "Tata Motors Passenger Vehicles": "TATAMOTORS",
    "HDFC Life Insurance": "HDFCLIFE",
    "Muthoot Finance": "MUTHOOTFIN",
    "Cholamandalam Investment": "CHOLAFIN",
    "Tata Power": "TATAPOWER",
    "Vedanta": "VEDL",
    "Britannia Industries": "BRITANNIA",
    "IRFC": "IRFC",
    "Bharat Petroleum": "BPCL",
    "Jindal Steel": "JINDALSTEL",
    "Union Bank of India": "UNIONBANK",
    "Apollo Hospitals": "APOLLOHOSP",
    "LTM": "LTIM",
    "Punjab National Bank": "PNB",
    "Tata Consumer Products": "TATACONSUM",
    "HDFC AMC": "HDFCAMC",
    "Bajaj Holdings & Investments": "BAJAJHLDNG",
    "Canara Bank": "CANBK",
    "Indus Towers": "INDUSTOWER",
    "Cipla": "CIPLA",
    "Indian Bank": "INDIANB",
    "Dr Reddys Laboratories": "DRREDDY",
    "Ambuja Cements": "AMBUJACEM",
    "Marico": "MARICO",
    "Bosch": "BOSCHLTD",
    "GAIL": "GAIL",
    "Godrej Consumer Products": "GODREJCP",
    "Zydus Life Science": "ZYDUSLIFE",
    "Lupin": "LUPIN",
    "Mankind Pharma": "MANKIND",
    "GMR Airports": "GMRAIRPORT",
    "Mazagon Dock Shipbuilders": "MAZDOCK",
    "Max Healthcare Institute": "MAXHEALTH",
    "Hero Motocorp": "HEROMOTOCO",
    "JSW Energy": "JSWENERGY",
    "Aditya Birla Capital": "ABCAPITAL",
    "United Spirits": "MCDOWELL-N",
    "Ashok Leyland": "ASHOKLEY",
    "Indian Hotels Company": "INDHOTEL",
    "ICICI Lombard General Insurance": "ICICIGI",
    "Bharat Forge": "BHARATFORG",
    "Shree Cement": "SHREECEM",
    "REC": "RECLTD",
    "Lodha Developers": "LODHA",
    "Waaree Energies": "WAAREEENER",
    "Aurobindo Pharma": "AUROPHARMA",
    "MCX": "MCX",
    "Steel Authority of India": "SAIL",
    "PB FinTech": "POLICYBZR",
    "Hindustan Petroleum": "HINDPETRO",
    "Oracle Financial Services Software": "OFSS",
    "Oil India": "OIL",
    "Dabur India": "DABUR",
    "Nykaa": "NYKAA",
    "NHPC": "NHPC",
    "Persistent Systems": "PERSISTENT",
    "SRF": "SRF",
    "NMDC": "NMDC",
    "ICICI Prudential Life Insurance": "ICICIPRULI",
    "Havells": "HAVELLS",
    "NALCO": "NATIONALUM",
    "Suzlon Energy": "SUZLON",
    "AU Small Finance Bank": "AUBANK",
    "Laurus Labs": "LAURUSLABS",
    "Fortis Healthcare": "FORTIS",
    "Dixon Technologies": "DIXON",
    "One 97 Communications": "PAYTM",
    "Indusind Bank": "INDUSINDBK",
    "Federal Bank": "FEDERALBNK",
    "Biocon": "BIOCON",
    "Swiggy": "SWIGGY",
    "Nippon Life India AMC": "NIPPONLIFE",
    "Yes Bank": "YESBANK",
    "L&T Finance": "LTF",
    "Alkem Laboratories": "ALKEM",
    "Phoenix Mills": "PHOENIXLTD",
    "Glenmark Pharmaceuticals": "GLENMARK",
    "Bank of India": "BANKINDIA",
    "UNO Minda": "UNOMINDA",
    "Info Edge": "NAUKRI",
    "Oberoi Realty": "OBEROIRLTY",
    "Prestige Estates Projects": "PRESTIGE",
    "IDFC First Bank": "IDFCFIRSTB",
    "SBI Cards": "SBICARD",
    "Colgate Palmolive": "COLPAL",
    "Tube Investment": "TIINDIA",
    "Max Financial Services": "MFSL",
    "Vishal Mega Mart": "VISHALMRT",
    "Rail Vikas Nigam": "RVNL",
    "UPL": "UPL",
    "APL Apollo Tubes": "APLAPOLLO",
    "Godrej Properties": "GODREJPROP",
    "Motilal Oswal Financial Services": "MOTILALOFS",
    "Patanjali Foods": "PATANJALI",
    "KEI Industries": "KEI",
    "Coforge": "COFORGE",
    "Bharat Dynamics": "BDL",
    "Supreme Industries": "SUPREMEIND",
    "360 One WAM": "360ONE",
    "Premier Energies": "PREMIERENE",
    "Page Industries": "PAGEIND",
    "Mphasis": "MPHASIS",
    "PI Industries": "PIIND",
    "Voltas": "VOLTAS",
    "Astral": "ASTRAL",
    "Petronet LNG": "PETRONET",
    "Cochin Shipyard": "COCHINSHIP",
    "Container Corporation of India": "CONCOR",
    "Sona BLW Precision Forgings": "SONACOMS",
    "Kalyan Jewellers": "KALYANKJIL",
    "IREDA": "IREDA",
    "Godfrey Phillips": "GODFRYPHLP",
    "Blue Star": "BLUESTARCO",
    "Dalmia Bharat": "DALMIACEM",
    "Delhivery": "DELHIVERY",
    "Bandhan Bank": "BANDHANBNK",
    "Angel One": "ANGELONE",
    "LIC Housing Finance": "LICHSGFIN",
    "Exide Industries": "EXIDEIND",
    "Jubilant FoodWorks": "JUBLFOOD",
    "PNB Housing Finance": "PNBHOUSING",
    "Manappuram Finance": "MANAPPURAM",
    "Nuvama Wealth Management": "NUVAMA",
    "Tata Elxsi": "TATAELXSI",
    "Force Motors": "FORCEMOT",
    "Amber Enterprises": "AMBER",
    "NBCC": "NBCC",
    "CDSL": "CDSL",
    "Kaynes Technology India": "KAYNES",
}


def get_futures_stock_ids(db_symbol_map):
    csv_path = os.path.join(base_dir, "data", "Dhan - Futures Stocks List - 22:05:26.csv")
    with open(csv_path) as f:
        names = [row["Name"] for row in csv.DictReader(f)]

    stock_ids = []
    not_found = []
    for name in names:
        nse = FUTURES_NAME_TO_NSE.get(name)
        if nse is None:
            not_found.append(f"no mapping: {name}")
            continue
        sid = db_symbol_map.get(nse)
        if sid is None:
            not_found.append(f"not in DB: {name} → {nse}")
            continue
        stock_ids.append(sid)

    if not_found:
        print(f"  {len(not_found)} stocks skipped:")
        for s in not_found[:15]:
            print(f"    {s}")
        if len(not_found) > 15:
            print(f"    ... +{len(not_found) - 15} more")

    print(f"Futures universe: {len(stock_ids)} stocks found in DB out of {len(names)}")
    return stock_ids


def get_month_ends():
    """Month-end dates starting from Dec 2023 (warmup) through today."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    dates = []
    current = datetime(2023, 11, 1) + relativedelta(months=1)
    while current <= today:
        dates.append(current - timedelta(days=1))
        current += relativedelta(months=1)
    return dates


def score_stocks(target_date, df_window, valid_stock_ids):
    """3M + 6M + 1Y volatility-adjusted momentum, z-scored and averaged."""
    scores = []
    unique_ids = set(df_window.index.get_level_values("stock_id").unique())

    for stock_id in valid_stock_ids:
        if stock_id not in unique_ids:
            continue
        try:
            df = df_window.xs(stock_id, level="stock_id")
            df = df[df.index <= target_date].sort_index()
            if len(df) < 252:
                continue

            df_log = np.log(df["close_price"] / df["close_price"].shift(1))
            vol = df_log.tail(252).std() * np.sqrt(252)
            if pd.isna(vol) or vol == 0:
                continue

            cur = df["close_price"].iloc[-1]

            def ret(days):
                if len(df) <= days:
                    return None
                return (cur / df["close_price"].iloc[-(days + 1)]) - 1

            r3m, r6m, r1y = ret(63), ret(126), ret(252)
            if None in [r3m, r6m, r1y]:
                continue

            scores.append(
                {
                    "stock_id": stock_id,
                    "mr_3m": r3m / vol,
                    "mr_6m": r6m / vol,
                    "mr_1y": r1y / vol,
                }
            )
        except (KeyError, IndexError):
            continue

    if not scores:
        return pd.DataFrame()

    df_s = pd.DataFrame(scores)
    for p in ["3m", "6m", "1y"]:
        col = f"mr_{p}"
        std = df_s[col].std()
        df_s[f"z_{p}"] = (df_s[col] - df_s[col].mean()) / std if std > 0 else 0.0

    df_s["weighted_z"] = (df_s["z_3m"] + df_s["z_6m"] + df_s["z_1y"]) / 3
    return df_s.sort_values("weighted_z", ascending=False).reset_index(drop=True)


def stock_return(stock_id, df_next, df_window, stock_map, score, side):
    """Compute return for one position. side = 'long' or 'short'."""
    stock_data = df_next[df_next["stock_id"] == stock_id].sort_values("date")

    if stock_data.empty:
        return {"symbol": stock_map.get(stock_id, "UNK"), "return": 0.0, "score": round(score, 2), "side": side}

    start_price = stock_data.iloc[0]["open_price"]
    if start_price is None or start_price == 0:
        return {"symbol": stock_map.get(stock_id, "UNK"), "return": 0.0, "score": round(score, 2), "side": side}

    end_price = stock_data.iloc[-1]["close_price"]
    raw_ret = (end_price - start_price) / start_price

    # Short position: flip sign
    ret = raw_ret if side == "long" else -raw_ret

    return {
        "symbol": stock_map.get(stock_id, "UNK"),
        "return": round(ret * 100, 2),
        "raw_return": round(raw_ret * 100, 2),
        "score": round(score, 2),
        "side": side,
    }


def get_benchmark_return(nifty, start_date, end_date):
    if nifty.empty:
        return 0.0
    n_start = nifty[nifty["date"] <= start_date]
    n_end = nifty[nifty["date"] <= end_date]
    if n_start.empty or n_end.empty:
        return 0.0
    return (n_end.iloc[-1]["close"] - n_start.iloc[-1]["close"]) / n_start.iloc[-1]["close"]


def process_period(
    rebalance_date,
    next_rebalance_date,
    master_df,
    futures_ids,
    stock_map,
    nifty,
    label_date=None,
    use_close_to_close=False,
):
    print(f"  Processing {rebalance_date.date()} → {next_rebalance_date.date()}")

    start_window = rebalance_date - timedelta(days=400)
    try:
        df_slice = master_df.loc[start_window:rebalance_date]
    except KeyError:
        return None
    if df_slice.empty:
        return None

    df_window = df_slice.reset_index()
    df_window = df_window.set_index(["stock_id", "date"])

    ranked = score_stocks(rebalance_date, df_window, futures_ids)
    if ranked.empty or len(ranked) < N_LONG + N_SHORT:
        print(f"    Not enough scored stocks: {len(ranked)}")
        return None

    long_stocks = ranked.head(N_LONG)
    short_stocks = ranked.tail(N_SHORT)

    try:
        df_next_slice = master_df.loc[rebalance_date + timedelta(days=1) : next_rebalance_date]
        all_ids = long_stocks["stock_id"].tolist() + short_stocks["stock_id"].tolist()
        df_next = df_next_slice[df_next_slice["stock_id"].isin(all_ids)].reset_index()
    except KeyError:
        df_next = pd.DataFrame()

    holdings = []
    long_returns = []
    short_returns = []

    score_map = ranked.set_index("stock_id")["weighted_z"].to_dict()

    for _, row in long_stocks.iterrows():
        r = stock_return(row["stock_id"], df_next, df_window, stock_map, score_map[row["stock_id"]], "long")
        holdings.append(r)
        long_returns.append(r["return"] / 100)

    for _, row in short_stocks.iterrows():
        r = stock_return(row["stock_id"], df_next, df_window, stock_map, score_map[row["stock_id"]], "short")
        holdings.append(r)
        short_returns.append(r["return"] / 100)

    avg_long = np.mean(long_returns) if long_returns else 0.0
    avg_short = np.mean(short_returns) if short_returns else 0.0

    # Dollar-neutral: 50% long + 50% short
    portfolio_return = (avg_long + avg_short) / 2

    bench_ret = get_benchmark_return(nifty, rebalance_date, next_rebalance_date)

    month_label = label_date or next_rebalance_date.strftime("%Y-%m")
    print(
        f"    Long: {avg_long:.2%}  Short(net): {avg_short:.2%}  Portfolio: {portfolio_return:.2%}  Bench: {bench_ret:.2%}"
    )

    return {
        "month": month_label,
        "portfolio_return": round(portfolio_return * 100, 2),
        "benchmark_return": round(bench_ret * 100, 2),
        "long_return": round(avg_long * 100, 2),
        "short_return": round(avg_short * 100, 2),
        "holdings": holdings,
    }


def calculate_comprehensive_metrics(monthly_results):
    if not monthly_results:
        return {
            "time_metrics": {"start": "-", "end": "-", "period": "-"},
            "capital_metrics": {"start_value": 0, "end_value": 0, "total_fees_paid": 0, "open_trade_pnl": 0},
            "return_metrics": {"total_return": 0, "benchmark_return": 0, "expectancy": 0, "net_return_after_fees": 0},
            "risk_metrics": {
                "max_drawdown": 0,
                "max_drawdown_duration": 0,
                "sharpe_ratio": 0,
                "calmar_ratio": 0,
                "omega_ratio": 0,
                "sortino_ratio": 0,
            },
            "exposure_metrics": {"max_gross_exposure": 200},
            "trade_statistics": {
                "total_trades": 0,
                "total_stock_transactions": 0,
                "win_rate": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "avg_winning_trade": 0,
                "avg_losing_trade": 0,
                "profit_factor": 0,
            },
        }

    port_rets = np.array([r["portfolio_return"] / 100 for r in monthly_results])
    bench_rets = np.array([r["benchmark_return"] / 100 for r in monthly_results])

    n = len(monthly_results)
    years = n / 12
    start_val = 100000
    cum = np.cumprod(1 + port_rets)
    cum_bench = np.cumprod(1 + bench_rets)
    end_val = start_val * cum[-1]

    total_ret = (end_val - start_val) / start_val
    bench_total = float(cum_bench[-1]) - 1

    cum_vals = start_val * cum
    running_max = np.maximum.accumulate(cum_vals)
    dds = (cum_vals - running_max) / running_max
    max_dd = float(np.min(dds))

    dd_dur = cur_dur = 0
    for d in dds:
        if d < 0:
            cur_dur += 1
            dd_dur = max(dd_dur, cur_dur)
        else:
            cur_dur = 0

    ann_ret = (1 + total_ret) ** (1 / years) - 1
    sharpe = (np.mean(port_rets) * 12) / (np.std(port_rets) * np.sqrt(12)) if np.std(port_rets) > 0 else 0
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
    down_rets = port_rets[port_rets < 0]
    sortino = (
        (np.mean(port_rets) * 12) / (np.std(down_rets) * np.sqrt(12))
        if len(down_rets) > 0 and np.std(down_rets) > 0
        else 0
    )
    gains = port_rets[port_rets > 0]
    losses = port_rets[port_rets < 0]
    omega = float(np.sum(gains)) / float(abs(np.sum(losses))) if len(losses) > 0 and np.sum(losses) != 0 else 0

    wins = int(np.sum(port_rets > 0))
    win_rate = wins / n * 100 if n > 0 else 0

    return {
        "time_metrics": {
            "start": monthly_results[0]["month"],
            "end": monthly_results[-1]["month"],
            "period": f"{n} months ({years:.1f} years)",
        },
        "capital_metrics": {
            "start_value": start_val,
            "end_value": round(end_val, 2),
            "total_fees_paid": 0,
            "open_trade_pnl": 0,
        },
        "return_metrics": {
            "total_return": round(total_ret * 100, 2),
            "benchmark_return": round(bench_total * 100, 2),
            "expectancy": round(float(np.mean(port_rets)) * 100, 2),
            "net_return_after_fees": 0,
        },
        "risk_metrics": {
            "max_drawdown": round(max_dd * 100, 2),
            "max_drawdown_duration": dd_dur,
            "sharpe_ratio": round(float(sharpe), 2),
            "calmar_ratio": round(float(calmar), 2),
            "omega_ratio": round(float(omega), 2),
            "sortino_ratio": round(float(sortino), 2),
        },
        "exposure_metrics": {"max_gross_exposure": 200},
        "trade_statistics": {
            "total_trades": n,
            "total_stock_transactions": 0,
            "win_rate": round(win_rate, 2),
            "best_trade": round(float(np.max(port_rets)) * 100, 2),
            "worst_trade": round(float(np.min(port_rets)) * 100, 2),
            "avg_winning_trade": round(float(np.mean(gains)) * 100, 2) if len(gains) > 0 else 0,
            "avg_losing_trade": round(float(np.mean(losses)) * 100, 2) if len(losses) > 0 else 0,
            "profit_factor": round(float(np.sum(gains)) / float(abs(np.sum(losses))), 2)
            if len(losses) > 0 and np.sum(losses) != 0
            else 0,
        },
    }


def calculate_stats_for_period(results, start_value=100000, initial_long=None, initial_short=None):
    total_txn = 0
    prev_long = initial_long or set()
    prev_short = initial_short or set()

    for r in results:
        cur_long = {h["symbol"] for h in r["holdings"] if h["side"] == "long"}
        cur_short = {h["symbol"] for h in r["holdings"] if h["side"] == "short"}
        if prev_long:
            total_txn += len(prev_long - cur_long) + len(cur_long - prev_long)
            total_txn += len(prev_short - cur_short) + len(cur_short - prev_short)
        else:
            total_txn += len(cur_long) + len(cur_short)
        prev_long = cur_long
        prev_short = cur_short

    port_val = start_value
    vals = []
    for r in results:
        port_val = port_val * (1 + r["portfolio_return"] / 100)
        vals.append(port_val)

    if not vals:
        return 0, 0, 0

    avg_val = np.mean(vals)
    fee_per_txn = (avg_val / (N_LONG + N_SHORT)) * 0.0025
    total_fees = total_txn * fee_per_txn
    net_val = vals[-1] - total_fees
    net_ret = ((net_val - start_value) / start_value) * 100

    return total_txn, total_fees, net_ret


def run_backtest():
    print("=== Long-Short Futures Momentum Backtest ===")
    db = DatabaseManager()
    session = db.Session()

    # Build symbol → stock_id map
    rows = session.execute(text("SELECT id, nse_symbol FROM stocks")).fetchall()
    db_symbol_map = {r.nse_symbol: r.id for r in rows}
    stock_map = {r.id: r.nse_symbol for r in rows}

    futures_ids = get_futures_stock_ids(db_symbol_map)
    set(futures_ids)

    print("Fetching Nifty benchmark...")
    try:
        nifty_raw = yf.download("^NSEI", start="2022-01-01", progress=False)
        if nifty_raw.empty:
            nifty = pd.DataFrame(columns=["date", "close"])
        else:
            if isinstance(nifty_raw.columns, pd.MultiIndex):
                nifty_raw.columns = nifty_raw.columns.get_level_values(0)
            nifty_raw = nifty_raw.reset_index()
            nifty_raw.columns = [c.lower() for c in nifty_raw.columns]
            close_col = "close" if "close" in nifty_raw.columns else "adj close"
            nifty = nifty_raw[["date", close_col]].rename(columns={close_col: "close"})
    except Exception as e:
        print(f"Benchmark fetch failed: {e}")
        nifty = pd.DataFrame(columns=["date", "close"])

    print("Loading price data...")
    result = session.execute(
        text("SELECT stock_id, date, close_price, open_price FROM daily_prices ORDER BY date ASC")
    ).fetchall()
    master_df = pd.DataFrame(result, columns=["stock_id", "date", "close_price", "open_price"])
    master_df["date"] = pd.to_datetime(master_df["date"])
    master_df = master_df.set_index("date")
    print(f"Loaded {len(master_df):,} price records.")

    dates = get_month_ends()
    output_path = os.path.join(base_dir, "web", "src", "data", "backtest_results_long_short.json")

    existing_map = {}
    if os.path.exists(output_path):
        try:
            with open(output_path) as f:
                data = json.load(f)
            combined = data.get("backtest_results", []) + data.get("current_performance", [])
            for r in combined:
                if "month" in r:
                    existing_map[r["month"]] = r
            print(f"Loaded {len(existing_map)} cached months.")
        except Exception as e:
            print(f"Could not load cache: {e}")

    all_results = []

    for i, rebalance_date in enumerate(dates[:-1]):
        next_rebalance_date = dates[i + 1]
        month_label = next_rebalance_date.strftime("%Y-%m")

        if month_label in existing_map:
            all_results.append(existing_map[month_label])
            continue

        res = process_period(rebalance_date, next_rebalance_date, master_df, futures_ids, stock_map, nifty)
        if res:
            all_results.append(res)

    # Current (live) month
    last_date = dates[-1]
    today = datetime.now()
    if today > last_date:
        cur_label = today.strftime("%Y-%m")
        all_results = [r for r in all_results if r["month"] != cur_label]
        res = process_period(last_date, today, master_df, futures_ids, stock_map, nifty, label_date=cur_label)
        if res:
            all_results.append(res)

    all_results.sort(key=lambda x: x["month"])

    backtest_cutoff = "2025-12"
    backtest_results = [r for r in all_results if r["month"] <= backtest_cutoff]
    current_results = [r for r in all_results if r["month"] > backtest_cutoff]

    # Only keep 2024+ for backtest metrics (discard Dec 2023 warmup)
    backtest_results = [r for r in backtest_results if r["month"] >= "2024-01"]

    print(f"\nBacktest months: {len(backtest_results)}")
    print(f"Current months: {len(current_results)}")

    bt_txn, bt_fees, bt_net = calculate_stats_for_period(backtest_results)
    bt_metrics = calculate_comprehensive_metrics(backtest_results)
    bt_metrics["trade_statistics"]["total_stock_transactions"] = bt_txn
    bt_metrics["capital_metrics"]["total_fees_paid"] = round(bt_fees, 2)
    bt_metrics["return_metrics"]["net_return_after_fees"] = round(bt_net, 2)

    last_long = (
        {h["symbol"] for h in backtest_results[-1]["holdings"] if h["side"] == "long"} if backtest_results else set()
    )
    last_short = (
        {h["symbol"] for h in backtest_results[-1]["holdings"] if h["side"] == "short"} if backtest_results else set()
    )
    cur_txn, cur_fees, cur_net = calculate_stats_for_period(
        current_results, initial_long=last_long, initial_short=last_short
    )

    cur_metrics = None
    if current_results:
        cur_metrics = calculate_comprehensive_metrics(current_results)
        cur_metrics["trade_statistics"]["total_stock_transactions"] = cur_txn
        cur_metrics["capital_metrics"]["total_fees_paid"] = round(cur_fees, 2)
        cur_metrics["return_metrics"]["net_return_after_fees"] = round(cur_net, 2)

    output = {
        "backtest_metrics": bt_metrics,
        "current_metrics": cur_metrics,
        "backtest_results": sorted(backtest_results, key=lambda x: x["month"], reverse=True),
        "current_performance": sorted(current_results, key=lambda x: x["month"], reverse=True),
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved → {output_path}")

    if backtest_results:
        total_long_wins = sum(1 for r in backtest_results if r["long_return"] > 0)
        total_short_wins = sum(1 for r in backtest_results if r["short_return"] > 0)
        print(f"Long leg win rate:  {total_long_wins / len(backtest_results):.1%}")
        print(f"Short leg win rate: {total_short_wins / len(backtest_results):.1%}")
        print(f"Net return (after fees): {bt_net:.2f}%")


if __name__ == "__main__":
    run_backtest()
