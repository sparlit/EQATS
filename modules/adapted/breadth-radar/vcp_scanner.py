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
╔══════════════════════════════════════════════════════════════════════╗
║  NSE VCP SCREENER — Minervini / O'Neil / Stage-2 Method              ║
║  Version 3.2 (Clean) |  Data: Yahoo Finance + NSE CSV  |  by Shibu   ║
║                                                                      ║
║  Scores every stock on:                                              ║
║    • Minervini Trend Template (Stage 2 confirmation)                 ║
║    • Prior Advance (momentum qualification)                          ║
║    • VCP: Drawdown, Volume dry-up, ATR contraction, Tightness        ║
║    • True VCP pullback sequence detection                            ║
║    • Smart Thematic Breadth (Railways, Defense, Pharma splits)       ║
║    • Potential BO & Pull Back Setup Detection                        ║
║    • Final Composite Score + Grade + Setup Type                      ║
║                                                                      ║
║  Install: pip install yfinance pandas openpyxl                       ║
║  Run:     python vcp_scanner.py                                      ║
║  Output:  scanner_results.html  - to NSE Breadth Radar               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
import signal
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, format="%(message)s")

# Configure UTF-8 encoding for Windows stdout/stderr to prevent charmap errors
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  CTRL+C OVERRIDE & CFFI POPUP SUPPRESSION
# ═══════════════════════════════════════════════════════════════════════
def silent_unraisable_hook(unraisable):
    if issubclass(unraisable.exc_type, KeyboardInterrupt):
        return
    sys.__unraisablehook__(unraisable)


sys.unraisablehook = silent_unraisable_hook


class GracefulInterruptHandler:
    def __init__(self):
        self.interrupted = False
        signal.signal(signal.SIGINT, self.handler)

    def handler(self, signum, frame):
        if self.interrupted:
            print("\n\n🛑 Force quitting...")
            sys.exit(1)
        self.interrupted = True
        print(
            "\n\n🛑 [Ctrl+C Detected] Please wait... finishing the current stock download to avoid breaking the network connection. The report will generate right after!"
        )


# ═══════════════════════════════════════════════════════════════════════
#  CONFIGURATION — edit these to tune the screener
# ═══════════════════════════════════════════════════════════════════════
CFG = {
    # Custom Links
    "tv_chart_url": "https://in.tradingview.com/chart/fZ5fwxUh/",
    # Liquidity filters
    "min_avg_volume_30d": 200_000,
    "min_avg_turnover_crore": 5,
    "min_market_cap_crore": 500,
    # Prior advance thresholds
    "min_30d_return": 15.0,  # %
    "min_60d_return": 25.0,  # %
    "pref_90d_return": 30.0,  # %
    # 52-week high proximity
    "max_dist_52w_high": -25.0,  # % — reject below this
    # Consolidation
    "max_drawdown_30d": -25.0,  # % — reject below this
    # ATR contraction
    "atr_contraction_threshold": 0.85,
    # Scoring weights
    "vcp_weight": 0.60,
    "leadership_weight": 0.40,
    # Output
    "top_n": 20,
    "delay_between_stocks": 0.25,
}


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════
def safe(v, default=0.0):
    try:
        f = float(v)
        return default if (np.isnan(f) or np.isinf(f)) else f
    except:
        return default


def atr(df, period):
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def sma(series, period):
    return series.rolling(period).mean()


BULK_STOCK_DATA = {}


# ═══════════════════════════════════════════════════════════════════════
#  DATA FETCH (Yahoo Finance)
# ═══════════════════════════════════════════════════════════════════════
def fetch_data(symbol, days=400):
    if symbol in BULK_STOCK_DATA:
        return BULK_STOCK_DATA[symbol], {}
    try:
        tk = yf.Ticker(symbol + ".NS")
        end = datetime.now()
        start = end - timedelta(days=days)
        df = tk.history(start=start, end=end, interval="1d")
        if df is None or len(df) < 252:
            return None, {}
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        info = {}
        try:
            raw = tk.fast_info
            info["market_cap"] = safe(getattr(raw, "market_cap", 0)) / 1e7  # → crore
        except:
            pass
        return df, info
    except:
        return None, {}


# ═══════════════════════════════════════════════════════════════════════
#  PART 2 — LIQUIDITY FILTER
# ═══════════════════════════════════════════════════════════════════════
def check_liquidity(df, info):
    avg_vol = df["Volume"].iloc[-30:].mean()
    avg_turnover = (df["Close"].iloc[-30:] * df["Volume"].iloc[-30:]).mean() / 1e7
    market_cap = safe(info.get("market_cap", 0))
    ok = (
        avg_vol >= CFG["min_avg_volume_30d"]
        and avg_turnover >= CFG["min_avg_turnover_crore"]
        and (market_cap >= CFG["min_market_cap_crore"] or market_cap == 0)
    )
    return ok, round(avg_vol), round(avg_turnover, 2), round(market_cap)


# ═══════════════════════════════════════════════════════════════════════
#  PART 3 — MINERVINI TREND TEMPLATE
# ═══════════════════════════════════════════════════════════════════════
def trend_template(df):
    c = df["Close"]
    e10 = ema(c, 10).iloc[-1]
    e20 = ema(c, 20).iloc[-1]
    e50 = ema(c, 50).iloc[-1]
    s150 = sma(c, 150).iloc[-1]
    s200 = sma(c, 200).iloc[-1]
    close = c.iloc[-1]

    conds = [
        close > e10,
        e10 > e20,
        e20 > e50,
        e50 > s150,
        s150 > s200,
        close > s150,
        close > s200,
    ]
    score = sum(conds) / len(conds) * 35
    passed = sum(conds)
    return round(score, 1), passed, len(conds)


# ═══════════════════════════════════════════════════════════════════════
#  PART 4 — PRIOR ADVANCE
# ═══════════════════════════════════════════════════════════════════════
def prior_advance(df):
    c = df["Close"]
    cur = c.iloc[-1]

    def ret(n):
        idx = max(0, len(c) - n - 1)
        p = c.iloc[idx]
        return round((cur / p - 1) * 100, 1) if p > 0 else 0.0

    r30 = ret(21)
    r60 = ret(42)
    r90 = ret(63)

    if r90 >= 100:
        pts = 20
    elif r90 >= 70:
        pts = 18
    elif r90 >= 50:
        pts = 15
    elif r90 >= 30:
        pts = 12
    elif r60 >= 30:
        pts = 10
    elif r30 >= 15:
        pts = 6
    else:
        pts = 0

    qualifies = r30 >= CFG["min_30d_return"] or r60 >= CFG["min_60d_return"]
    return r30, r60, r90, pts, qualifies


# ═══════════════════════════════════════════════════════════════════════
#  PART 5 — 52-WEEK HIGH PROXIMITY
# ═══════════════════════════════════════════════════════════════════════
def high_proximity(df):
    c = df["Close"]
    h252 = df["High"].iloc[-252:].max()
    l252 = df["Low"].iloc[-252:].min()
    cur = c.iloc[-1]
    dist = round((cur - h252) / h252 * 100, 1)

    if dist >= -5:
        pts = 20
    elif dist >= -10:
        pts = 15
    elif dist >= -15:
        pts = 10
    elif dist >= -20:
        pts = 5
    else:
        pts = 0

    qualifies = dist >= CFG["max_dist_52w_high"]
    return dist, pts, round(h252, 2), round(l252, 2), qualifies


# ═══════════════════════════════════════════════════════════════════════
#  PART 6 — CONSOLIDATION / DRAWDOWN
# ═══════════════════════════════════════════════════════════════════════
def consolidation(df):
    c = df["Close"]
    h30 = df["High"].iloc[-30:].max()
    cur = c.iloc[-1]
    drawdown = round((cur - h30) / h30 * 100, 1)

    if drawdown >= -5:
        pts = 20
    elif drawdown >= -10:
        pts = 16
    elif drawdown >= -15:
        pts = 12
    elif drawdown >= -20:
        pts = 8
    elif drawdown >= -25:
        pts = 4
    else:
        pts = 0

    qualifies = drawdown >= CFG["max_drawdown_30d"]
    base_type = (
        "Shelf"
        if drawdown >= -5
        else "Flat Base"
        if drawdown >= -15
        else "Cup"
        if drawdown >= -25
        else "Too Deep"
    )
    return drawdown, pts, qualifies, base_type


# ═══════════════════════════════════════════════════════════════════════
#  PART 7 — VOLUME DRY-UP
# ═══════════════════════════════════════════════════════════════════════
def volume_dryup(df):
    v = df["Volume"]
    vol_r = v.iloc[-10:].mean()
    vol_l = v.iloc[-30:-10].mean()
    if vol_l <= 0:
        return 0.0, 0, False
    contraction = (vol_r / vol_l - 1) * 100
    dryup = contraction < 0

    if contraction <= -60:
        pts = 20
    elif contraction <= -40:
        pts = 16
    elif contraction <= -20:
        pts = 12
    elif contraction < 0:
        pts = 6
    else:
        pts = 0

    return round(contraction, 1), pts, dryup


# ═══════════════════════════════════════════════════════════════════════
#  PART 8 — ATR CONTRACTION
# ═══════════════════════════════════════════════════════════════════════
def atr_contraction(df):
    if len(df) < 35:
        return 1.0, 0, False
    a10 = atr(df, 10)
    a30 = atr(df, 30)
    if a30 <= 0:
        return 1.0, 0, False
    ratio = round(a10 / a30, 3)

    if ratio < 0.60:
        pts = 20
    elif ratio < 0.70:
        pts = 16
    elif ratio < 0.80:
        pts = 12
    elif ratio < 0.85:
        pts = 8
    else:
        pts = 0

    contracting = ratio < CFG["atr_contraction_threshold"]
    return ratio, pts, contracting


# ═══════════════════════════════════════════════════════════════════════
#  PART 9 — TIGHTNESS DETECTION
# ═══════════════════════════════════════════════════════════════════════
def tightness(df):
    h10 = df["High"].iloc[-10:].max()
    l10 = df["Low"].iloc[-10:].min()
    if l10 <= 0:
        return 99.0, 0
    tight = round((h10 - l10) / l10 * 100, 1)

    if tight <= 5:
        pts = 20
    elif tight <= 8:
        pts = 16
    elif tight <= 10:
        pts = 12
    elif tight <= 15:
        pts = 6
    else:
        pts = 0

    return tight, pts


# ═══════════════════════════════════════════════════════════════════════
#  PART 10 — TRUE VCP PULLBACK SEQUENCE
# ═══════════════════════════════════════════════════════════════════════
def vcp_pullbacks(df):
    c = df["Close"].iloc[-90:].reset_index(drop=True)
    n = len(c)
    troughs = []
    for i in range(5, n - 5):
        if c.iloc[i] == c.iloc[i - 5 : i + 5].min():
            troughs.append((i, c.iloc[i]))

    peaks = []
    for i in range(5, n - 5):
        if c.iloc[i] == c.iloc[i - 5 : i + 5].max():
            peaks.append((i, c.iloc[i]))

    pullbacks = []
    for t_idx, t_val in troughs:
        prior_peaks = [(p_i, p_v) for p_i, p_v in peaks if p_i < t_idx]
        if not prior_peaks:
            continue
        p_i, p_v = prior_peaks[-1]
        if p_v > 0:
            depth = (t_val - p_v) / p_v * 100
            pullbacks.append(round(abs(depth), 1))

    pullbacks = pullbacks[-4:]

    bonus = 0
    if len(pullbacks) >= 2:
        contractions = sum(1 for i in range(1, len(pullbacks)) if pullbacks[i] < pullbacks[i - 1])
        ratio = contractions / (len(pullbacks) - 1)
        if ratio == 1.0:
            bonus = 10
        elif ratio >= 0.67:
            bonus = 7
        elif ratio >= 0.5:
            bonus = 4
        else:
            bonus = 1

    return bonus, pullbacks


# ═══════════════════════════════════════════════════════════════════════
#  PART 11 — RS PROXY
# ═══════════════════════════════════════════════════════════════════════
def rs_proxy_raw(df):
    c = df["Close"]
    cur = c.iloc[-1]

    def ret(n):
        idx = max(0, len(c) - n - 1)
        p = c.iloc[idx]
        return (cur / p - 1) * 100 if p > 0 else 0.0

    r63 = ret(63)
    r126 = ret(126)
    r252 = ret(252)
    composite = r63 * 0.4 + r126 * 0.3 + r252 * 0.3
    return composite, r63, r126, r252


def compute_rs_scores(results):
    composites = [r["_rs_composite"] for r in results]
    if not composites:
        return results
    mn, mx = min(composites), max(composites)
    rng = mx - mn if mx != mn else 1
    for r in results:
        r["rs_score"] = round((r["_rs_composite"] - mn) / rng * 100, 1)
    return results


# ═══════════════════════════════════════════════════════════════════════
#  PART 12 — SETUP DETECTION (Pocket Pivot, Potential BO, Pull Back)
# ═══════════════════════════════════════════════════════════════════════
def pocket_pivot(df):
    if len(df) < 12:
        return False
    c = df["Close"]
    v = df["Volume"]
    e10_s = ema(c, 10)
    today_vol = v.iloc[-1]
    today_cls = c.iloc[-1]
    today_e10 = e10_s.iloc[-1]

    prior = df.iloc[-11:-1]
    down_days = prior[prior["Close"] < prior["Close"].shift(1).fillna(prior["Close"])]
    if down_days.empty:
        return False

    max_down_vol = down_days["Volume"].max()
    return bool(today_cls > today_e10 and today_vol > max_down_vol)


def potential_bo(df, r60, r90, dist52):
    if len(df) < 200:
        return False
    c = df["Close"]
    v = df["Volume"]
    c0 = c.iloc[-1]

    s50 = sma(c, 50).iloc[-1]
    s200 = sma(c, 200).iloc[-1]
    h30 = df["High"].iloc[-30:].max()

    if not (c0 > s50 and s50 > s200):
        return False
    if not (r60 >= 30 or r90 >= 30):
        return False
    if dist52 < -25:
        return False

    dist_to_h30 = (c0 - h30) / h30 * 100
    if not (-12 <= dist_to_h30 <= -2):
        return False

    v3 = v.iloc[-3:].mean()
    v20 = v.iloc[-20:].mean()
    return not v3 >= v20


def pull_back_setup(df):
    if len(df) < 252:
        return False
    c = df["Close"]
    h = df["High"]
    c0 = c.iloc[-1]

    h252 = h.iloc[-252:].max()
    h_recent = h.iloc[-20:].max()

    hit_ath_recently = h_recent >= h252 * 0.98
    drawdown = (c0 - h_recent) / h_recent * 100
    e50 = ema(c, 50).iloc[-1]

    return bool(hit_ath_recently and -12 <= drawdown <= -3 and c0 > e50)


# ═══════════════════════════════════════════════════════════════════════
#  PARTS 13-16 — SCORING & GRADING
# ═══════════════════════════════════════════════════════════════════════
def leadership_score(prox_pts, trend_pts, rs_score, avg_turnover):
    liq = min(15, avg_turnover / 10 * 15) if avg_turnover < 10 else 15
    rs_pts = rs_score * 0.30
    total = min(100, prox_pts + trend_pts + rs_pts + liq)
    return round(total, 1)


def vcp_score(adv_pts, dd_pts, vol_pts, atr_pts, tight_pts):
    return min(100, adv_pts + dd_pts + vol_pts + atr_pts + tight_pts)


def composite_score(vcp, leadership):
    return round(vcp * CFG["vcp_weight"] + leadership * CFG["leadership_weight"], 1)


def grade(score):
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 60:
        return "C"
    else:
        return "REJECT"


# ═══════════════════════════════════════════════════════════════════════
#  INDUSTRY GROUP MAPPINGS & CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════
PSU_BANKS_TICKERS = {
    "SBIN",
    "PNB",
    "BOB",
    "CANBK",
    "UNIONBANK",
    "INDIANB",
    "UCOBANK",
    "BANKBARODA",
    "BANKINDIA",
    "MAHABANK",
    "CENTRALBK",
    "IOB",
    "PSB",
}
PRIVATE_BANKS_TICKERS = {
    "HDFCBANK",
    "ICICIBANK",
    "KOTAKBANK",
    "AXISBANK",
    "INDUSINDBK",
    "FEDERALBNK",
    "IDFCFIRSTB",
    "BANDHANBNK",
    "YESBANK",
    "CUB",
    "KTKBANK",
    "RBLBANK",
    "SOUTHBANK",
    "CSBBANK",
    "AUBANK",
    "INDUSIND",
}
INSURANCE_TICKERS = {
    "HDFCLIFE",
    "SBILIFE",
    "ICICIPRULI",
    "LIC",
    "GICRE",
    "NIACL",
    "MAXFSL",
    "ICICIGI",
    "STARHEALTH",
}
AMC_TICKERS = {"HDFCAMC", "NAM-INDIA", "UTIAMC", "ABSLAMC"}
CAPITAL_MARKETS_TICKERS = {
    "CDSL",
    "BSE",
    "MCX",
    "CAMS",
    "KFINTECH",
    "ANGELONE",
    "ISEC",
    "MUTHOOTOT",
    "5PAISA",
    "ANANDRATHI",
    "GEODJITFSL",
    "MOTILALOFS",
}

CABLES_TICKERS = {"POLYCAB", "KEI", "RRKABEL", "FINCABLES"}
TRANSFORMERS_TICKERS = {"VOLTAMP", "CGPOWER", "TRIL", "TRANSFORM", "SCHNEIDER"}
BEARINGS_TICKERS = {"SKFINDIA", "TIMKEN", "SHAFFLER", "SCHAEFFLER", "HARSHA"}
COMPRESSORS_TICKERS = {"ELGIEQUIP", "KPIL", "KIRLPNU"}
HVAC_TICKERS = {"VOLTAS", "BLUESTARCO", "HITACHIHAM"}

COPPER_TICKERS = {"HINDCOPPER"}
STEEL_TICKERS = {
    "TATASTEEL",
    "JSWSTEEL",
    "SAIL",
    "JSL",
    "JINDALSTEL",
    "KALYANISTEEL",
    "APLAPOLLO",
    "WELCORP",
    "MAHSEAMLES",
}
ALUMINIUM_TICKERS = {"HINDALCO", "NATIONALUM"}
MINING_TICKERS = {"COALINDIA", "NMDC", "GMDC"}
EXPLOSIVES_TICKERS = {"SOLARINDS", "PREMEXPLN"}
DYES_PIGMENTS_TICKERS = {"BODALCHEM", "KIRIINDUS", "SUDARSCHEM", "MEGH"}

GAS_TRADING_TICKERS = {"GAIL", "GSPL"}
CGD_TICKERS = {"IGL", "MGL", "ATGL", "GUJGASLTD"}
SOLAR_TICKERS = {"TATAPOWER", "ADANIGREEN", "SWSOLAR", "WAAREEENER", "WEBSOL"}
POWER_EQUIP_TICKERS = {"BHEL", "SUZLON", "INOXWIND", "GET&D"}

CDMO_TICKERS = {"DIVISLAB", "SYNGENE", "SUVENPHAR", "LAURUSLABS"}
DIAGNOSTICS_TICKERS = {"LALPATHLAB", "METROPOLIS", "THYROCARE", "VIJAYA"}
MEDICAL_DEVICES_TICKERS = {"POLYMED"}

COMMERCIAL_VEH_TICKERS = {"ASHOKLEY", "SMLISUZU"}
PASSENGER_VEH_TICKERS = {"MARUTI", "M&M", "TATAMOTORS", "HYUNDAI"}
TYRES_TICKERS = {"MRF", "APOLLOTYRE", "CEATLTD", "JKTYRE", "BALKRISIND"}
EV_COMPONENTS_TICKERS = {"SONACOMS", "MINDACORP", "UNOMINDA"}
BATTERIES_TICKERS = {"EXIDEIND", "AMARAJABAT", "ARE&M"}
TRACTORS_TICKERS = {"ESCORTS", "VSTTILLERS"}

RETAIL_TICKERS = {"TRENT", "DMART", "ABFRL", "SHOPERSTOP", "VMART", "ETHOSLTD"}
JEWELLERY_TICKERS = {"TITAN", "KALYANKJIL", "SENCO", "RAJESHEXPO"}
FOOTWEAR_TICKERS = {"BATAINDIA", "METROBRAND", "RELAXO", "CAMPUS"}
RESTAURANTS_QSR_TICKERS = {"JUBLFOOD", "DEVYANI", "WESTLIFE", "RBA", "SAPPHIRE"}
TEXTILES_TICKERS = {
    "PAGEIND",
    "ARVIND",
    "VTL",
    "RAYMOND",
    "WELSPUNLIV",
    "ALOKIND",
    "GARFIBRES",
    "GOKEX",
    "KPRMILL",
}

AEROSPACE_DEFENCE_TICKERS = {
    "HAL",
    "BEL",
    "BDL",
    "ASTRAMICRO",
    "PARAS",
    "DATAPATTNS",
    "ZENTEC",
    "MTARTECH",
    "DYNAMATECH",
    "IDEAFORGE",
}
SHIPBUILDING_TICKERS = {"MAZDOCK", "COCHINSHIP", "GRSE"}
EMS_TICKERS = {"DIXON", "KAYNES", "SYRMA", "AVALON"}
DATA_CENTERS_TICKERS = {"NETWEB", "ANANTRAJ"}
RAILWAY_TICKERS = {
    "IRFC",
    "IRCTC",
    "RVNL",
    "IRCON",
    "RITES",
    "TITAGARH",
    "TEXMACO",
    "RAILTEL",
    "JWL",
}
AGRO_TICKERS = {"CHAMBLFERT", "FACT", "COROMANDEL", "GNFC", "GSFC", "RCF", "UPL"}

FILTER_STOCK_MAP = None

MS_GROUP_TO_SECTOR = {
    "Aerospace/Defense": "Defense",
    "Apparel-Clothing Mfg": "Textiles",
    "Apparel-Shoes & Rel Mfg": "Consumer Durables",
    "Auto Manufacturers": "Automobile and Auto Components",
    "Auto/Truck-Original Eqp": "Automobile and Auto Components",
    "Auto/Truck-Replace Parts": "Automobile and Auto Components",
    "Auto/Truck-Tires & Misc": "Automobile and Auto Components",
    "Banks-Money Center": "Banks",
    "Beverages-Alcoholic": "Fast Moving Consumer Goods",
    "Beverages-Non-Alcoholic": "Fast Moving Consumer Goods",
    "Bldg-A/C & Heating Prds": "Consumer Durables",
    "Bldg-Cement/Concrt/Ag": "Construction Materials",
    "Bldg-Constr Prds/Misc": "Capital Goods",
    "Bldg-Heavy Construction": "Construction",
    "Bldg-Resident/Comml": "Realty",
    "Chemicals-Agricultural": "Agrochemicals & Fertilizers",
    "Chemicals-Basic": "Specialty Chemicals",
    "Chemicals-Paints": "Consumer Durables",
    "Chemicals-Plastics": "Specialty Chemicals",
    "Chemicals-Specialty": "Specialty Chemicals",
    "Comml Svcs-Advertising": "Media Entertainment & Publication",
    "Comml Svcs-Consulting": "Services",
    "Comml Svcs-Healthcare": "Hospitals & Healthcare",
    "Comml Svcs-Market Rsrch": "Services",
    "Comml Svcs-Outsourcing": "Services",
    "Comp Sftwr-Spec Enterprs": "Information Technology",
    "Computer Sftwr-Database": "Information Technology",
    "Computer Sftwr-Desktop": "Information Technology",
    "Computer-Hardware/Perip": "Information Technology",
    "Computer-Networking": "Information Technology",
    "Computer-Tech Services": "Information Technology",
    "Consumer Prod-Electronic": "Consumer Durables",
    "Consumer Prod-Specialty": "Consumer Durables",
    "Consumer Svcs-Education": "Consumer Services",
    "Cosmetics/Personal Care": "Fast Moving Consumer Goods",
    "Diversified Operations": "Diversified",
    "Elec-Misc Products": "Capital Goods",
    "Electrical-Power/Equipmt": "Capital Goods",
    "Energy-Alternative/Other": "Power",
    "Energy-Coal": "Oil Gas & Consumable Fuels",
    "Energy-Solar": "Power",
    "Finance-Commercial Loans": "NBFCs & Finance",
    "Finance-Consumer Loans": "NBFCs & Finance",
    "Finance-Crdtcard/Pmtpr": "NBFCs & Finance",
    "Finance-Invest Bnk/Bkrs": "NBFCs & Finance",
    "Finance-Investment Mgmt": "NBFCs & Finance",
    "Finance-Mrtg&Rel Svc": "NBFCs & Finance",
    "Finance-Property Reit": "Realty",
    "Financial Svcs-Specialty": "NBFCs & Finance",
    "Food-Grain & Related": "Fast Moving Consumer Goods",
    "Food-Misc Preparation": "Fast Moving Consumer Goods",
    "Food-Packaged": "Fast Moving Consumer Goods",
    "Hsehold-Appliances/Wares": "Consumer Durables",
    "Insurance-Acc & Health": "NBFCs & Finance",
    "Insurance-Brokers": "NBFCs & Finance",
    "Insurance-Diversified": "NBFCs & Finance",
    "Insurance-Life": "NBFCs & Finance",
    "Insurance-Prop/Cas/Titl": "NBFCs & Finance",
    "Internet-Content": "Consumer Services",
    "Leisure-Lodging": "Consumer Services",
    "Leisure-Movies & Related": "Media Entertainment & Publication",
    "Leisure-Services": "Consumer Services",
    "Leisure-Travel Booking": "Consumer Services",
    "Machinery-Constr/Mining": "Capital Goods",
    "Machinery-Farm": "Automobile and Auto Components",
    "Machinery-Gen Industrial": "Capital Goods",
    "Machinery-Mtl Hdlg/Autmn": "Capital Goods",
    "Machinery-Tools & Rel": "Capital Goods",
    "Media-Radio/Tv": "Media Entertainment & Publication",
    "Medical-Biomed/Biotech": "Pharma",
    "Medical-Diversified": "Pharma",
    "Medical-Generic Drugs": "Pharma",
    "Medical-Hospitals": "Hospitals & Healthcare",
    "Medical-Products": "Pharma",
    "Medical-Research Eqp/Svc": "Pharma",
    "Medical-Services": "Hospitals & Healthcare",
    "Medical-Supplies": "Pharma",
    "Medical-Systems/Equip": "Pharma",
    "Medical-Whlsle Drg/Suppl": "Pharma",
    "Metal Proc & Fabrication": "Metals & Mining",
    "Mining-Metal Ores": "Metals & Mining",
    "Oil&Gas-Integrated": "Oil Gas & Consumable Fuels",
    "Oil&Gas-Intl Expl&Prod": "Oil Gas & Consumable Fuels",
    "Oil&Gas-Refining/Mktg": "Oil Gas & Consumable Fuels",
    "Oil&Gas-Transprt/Pipelne": "Oil Gas & Consumable Fuels",
    "Real Estate Dvlpmt/Ops": "Realty",
    "Retail-Department Stores": "Consumer Services",
    "Retail-Internet": "Consumer Services",
    "Retail-Mail Order&Direct": "Consumer Services",
    "Retail-Restaurants": "Consumer Services",
    "Retail-Specialty": "Consumer Services",
    "Retail-Super/Mini Mkts": "Consumer Services",
    "Retail/Whlsle-Jewelry": "Consumer Durables",
    "Steel-Producers": "Metals & Mining",
    "Steel-Specialty Alloys": "Metals & Mining",
    "Telecom Svcs-Cable/Satl": "Telecommunication",
    "Telecom Svcs-Integrated": "Telecommunication",
    "Telecom Svcs-Wireless": "Telecommunication",
    "Telecom-Consumer Prods": "Telecommunication",
    "Telecom-Infrastructure": "Telecommunication",
    "Tobacco": "Fast Moving Consumer Goods",
    "Transportation-Airline": "Services",
    "Transportation-Equip Mfg": "Capital Goods",
    "Transportation-Logistics": "Services",
    "Transportation-Ship": "Services",
    "Trucks & Parts-Hvy Duty": "Automobile and Auto Components",
    "Utility-Electric Power": "Power",
    "Utility-Gas Distribution": "Oil Gas & Consumable Fuels",
}


def get_industry_group(symbol, company, industry):
    global FILTER_STOCK_MAP
    sym = symbol.upper().replace(".NS", "")

    # Lazy load the Filter_India_Stocks.csv
    if FILTER_STOCK_MAP is None:
        FILTER_STOCK_MAP = {}
        try:
            csv_path = Path(__file__).resolve().parent / "Filter_India_Stocks.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path, index_col=False)
                for _, row in df.iterrows():
                    s_code = str(row["Symbol"]).strip().upper()
                    gp = (
                        str(row["Industry_Group"]).strip()
                        if pd.notna(row["Industry_Group"])
                        else ""
                    )
                    if s_code and gp:
                        FILTER_STOCK_MAP[s_code] = gp
        except Exception as e:
            logging.warning(f"Error loading Filter_India_Stocks.csv: {e}")

    # Check if stock exists in CSV
    if FILTER_STOCK_MAP and sym in FILTER_STOCK_MAP:
        raw_group = FILTER_STOCK_MAP[sym]
        parent = MS_GROUP_TO_SECTOR.get(raw_group, "Diversified")
        group = raw_group
        if not group.endswith(" IN"):
            group = group + " IN"
        return group, parent

    # Fallback to default keyword heuristic logic if not found in CSV
    comp = company.upper()
    ind = industry.upper()

    # 0. Railways
    railway_tickers = {
        "IRFC",
        "IRCTC",
        "RVNL",
        "IRCON",
        "RITES",
        "TITAGARH",
        "TEXMACO",
        "RAILTEL",
        "JWL",
    }
    if sym in railway_tickers or "RAILWAY" in comp:
        return "Transportation-Rail IN", "Railways"

    # 0.5. Defense / Aerospace
    if sym in AEROSPACE_DEFENCE_TICKERS or any(
        x in comp for x in ["AEROSPACE", "DEFENCE", "DEFENSE", "DYNAMICS"]
    ):
        return "Aerospace/Defense IN", "Defense"

    # 1. Financials
    if "FINANCIAL" in ind or "BANKS" in ind:
        if sym in PSU_BANKS_TICKERS or any(
            x in comp
            for x in [
                "STATE BANK",
                "PUNJAB NATIONAL",
                "BANK OF BARODA",
                "CANARA",
                "UNION BANK",
                "INDIAN BANK",
                "UCO BANK",
                "BANK OF INDIA",
                "MAHARASHTRA",
                "CENTRAL BANK",
                "OVERSEAS",
                "SHUBH",
                "PSU",
            ]
        ):
            return "Banks-Money Center IN", "Banks"
        if sym in PRIVATE_BANKS_TICKERS or any(
            x in comp
            for x in [
                "HDFC BANK",
                "ICICI BANK",
                "KOTAK",
                "AXIS",
                "INDUSIND",
                "FEDERAL",
                "IDFC FIRST",
                "BANDHAN",
                "YES BANK",
                "CITY UNION",
                "KARUR VYSYA",
                "RBL",
                "SOUTH INDIAN",
                "CSB BANK",
                "AU SMALL",
            ]
        ):
            return "Banks-Money Center IN", "Banks"
        if sym in INSURANCE_TICKERS or any(
            x in comp for x in ["INSURANCE", "LIFE", "GENERAL INS", "ASSURANCE", "MAX FINANCIAL"]
        ):
            return "Insurance-Life IN", "NBFCs & Finance"
        if (
            sym in AMC_TICKERS
            or "AMC" in comp
            or "MUTUAL FUND" in comp
            or "ASSET MANAGEMENT" in comp
            or "NIPPON LIFE" in comp
        ):
            return "Finance-Investment Mgmt IN", "NBFCs & Finance"
        if (
            sym in CAPITAL_MARKETS_TICKERS
            or "CAPITAL MARKETS" in ind
            or any(
                x in comp
                for x in [
                    "CDSL",
                    "BSE",
                    "MCX",
                    "CAMS",
                    "KFIN",
                    "ANGEL ONE",
                    "SECURITIES",
                    "WEALTH",
                    "BROKING",
                    "INVESTMENT",
                ]
            )
        ):
            return "Finance-Invest Bnk/Bkrs IN", "NBFCs & Finance"
        return "Finance-Consumer Loans IN", "NBFCs & Finance"

    # 2. Industrials
    if "CAPITAL GOODS" in ind or "INDUSTRIAL" in ind or "MACHINERY" in ind:
        if sym in AEROSPACE_DEFENCE_TICKERS or any(
            x in comp for x in ["AEROSPACE", "DEFENCE", "DEFENSE", "DYNAMICS"]
        ):
            return "Aerospace/Defense IN", "Defense"
        if (
            sym in SHIPBUILDING_TICKERS
            or "SHIPYARD" in comp
            or "SHIPBUILD" in comp
            or "MAZAGON" in comp
        ):
            return "Transportation-Ship IN", "Defense"

        if sym in CABLES_TICKERS or "CABLE" in comp or "RR KABEL" in comp:
            return "Electrical-Power/Equipmt IN", "Capital Goods"
        if sym in TRANSFORMERS_TICKERS or "TRANSFORMER" in comp or "SCHNEIDER" in comp:
            return "Electrical-Power/Equipmt IN", "Capital Goods"
        if sym in BEARINGS_TICKERS or "BEARING" in comp:
            return "Machinery-Gen Industrial IN", "Capital Goods"
        if sym in COMPRESSORS_TICKERS or "COMPRESSOR" in comp or "PNEUMATIC" in comp:
            return "Machinery-Gen Industrial IN", "Capital Goods"
        if sym in HVAC_TICKERS or "VOLTAS" in comp or "BLUE STAR" in comp:
            return "Bldg-A/C &amp; Heating Prds IN", "Capital Goods"
        if "AUTOMATION" in comp or "HONEYWELL" in comp:
            return "Machinery-Gen Industrial IN", "Capital Goods"
        return "Machinery-Gen Industrial IN", "Capital Goods"

    # 3. Materials
    if "METALS & MINING" in ind or "METALS" in ind or "MINING" in ind or "MATERIALS" in ind:
        if sym in COPPER_TICKERS or "COPPER" in comp:
            return "Mining-Metal Ores IN", "Metals & Mining"
        if sym in ALUMINIUM_TICKERS or "ALUMINIUM" in comp or "NALCO" in comp:
            return "Mining-Metal Ores IN", "Metals & Mining"
        if (
            sym in MINING_TICKERS
            or "MINING" in ind
            or "COAL INDIA" in comp
            or "NMDC" in comp
            or "GMDC" in comp
        ):
            return "Mining-Metal Ores IN", "Metals & Mining"
        if (
            sym in STEEL_TICKERS
            or "STEEL" in comp
            or "PIPE" in comp
            or "APOLLO TUBES" in comp
            or "WELSPUN CORP" in comp
        ):
            return "Steel-Producers IN", "Metals & Mining"
        return "Metal Proc &amp; Fabrication IN", "Metals & Mining"

    if "CHEMICALS" in ind:
        agro_keywords = ["AGRICULTURAL", "FERTILIZER", "AGRI"]
        agro_tickers = {"CHAMBLFERT", "FACT", "COROMANDEL", "GNFC", "GSFC", "RCF", "UPL"}
        if any(kw in comp for kw in agro_keywords) or sym in agro_tickers:
            return "Chemicals-Agricultural IN", "Agrochemicals & Fertilizers"
        if sym in EXPLOSIVES_TICKERS or "EXPLOSIVE" in comp or "SOLAR IND" in comp:
            return "Chemicals-Specialty IN", "Specialty Chemicals"
        if (
            sym in DYES_PIGMENTS_TICKERS
            or "DYE" in comp
            or "PIGMENT" in comp
            or "SUDARSHAN" in comp
        ):
            return "Chemicals-Specialty IN", "Specialty Chemicals"
        return "Chemicals-Specialty IN", "Specialty Chemicals"

    # 4. Energy
    if "POWER" in ind or "OIL GAS" in ind or "ENERGY" in ind:
        if sym in GAS_TRADING_TICKERS or "GAIL" in comp or "GSPL" in comp:
            return "Utility-Gas Distribution IN", "Oil Gas & Consumable Fuels"
        if (
            sym in CGD_TICKERS
            or "GUJARAT GAS" in comp
            or "INDRAPRASTHA GAS" in comp
            or "MAHANAGAR GAS" in comp
            or "ADANI TOTAL" in comp
        ):
            return "Utility-Gas Distribution IN", "Oil Gas & Consumable Fuels"
        if sym in SOLAR_TICKERS or "SOLAR" in comp or "ADANI GREEN" in comp or "WAAREE" in comp:
            return "Energy-Solar IN", "Power"
        if (
            sym in POWER_EQUIP_TICKERS
            or "SUZLON" in comp
            or "WIND" in comp
            or "BHEL" in comp
            or "GET&D" in comp
        ):
            return "Electrical-Power/Equipmt IN", "Power"
        return "Energy-Alternative/Other IN", "Power"

    # 5. Healthcare
    if "HEALTHCARE" in ind or "PHARMACEUTICALS" in ind:
        if "CHEMICAL" in comp and "PHARM" not in comp:
            return "Chemicals-Specialty IN", "Specialty Chemicals"
        if (
            sym in CDMO_TICKERS
            or "CDMO" in comp
            or "DIVI'S" in comp
            or "SYNGENE" in comp
            or "LAURUS" in comp
        ):
            return "Medical-Biomed/Biotech IN", "Pharma"
        if (
            sym in DIAGNOSTICS_TICKERS
            or "DIAGNOSTIC" in comp
            or "LAL PATH" in comp
            or "METROPOLIS" in comp
        ):
            return "Medical-Services IN", "Hospitals & Healthcare"
        if sym in MEDICAL_DEVICES_TICKERS or "MEDICURE" in comp or "DEVICE" in comp:
            return "Medical-Products IN", "Hospitals & Healthcare"
        if (
            "PHARMA" in comp
            or "LAB" in comp
            or "BIOTECH" in comp
            or "DRUG" in comp
            or "MEDICINE" in comp
        ):
            return "Medical-Generic Drugs IN", "Pharma"
        return "Medical-Hospitals IN", "Hospitals & Healthcare"

    # 6. Auto
    if "AUTO" in ind or "VEHICLE" in ind:
        if sym in TYRES_TICKERS or "TYRE" in comp or "CEAT" in comp or "MRF" in comp:
            return "Auto/Truck-Tires &amp; Misc  IN", "Automobile and Auto Components"
        if sym in EV_COMPONENTS_TICKERS or "EV" in comp or "SONA BLW" in comp or "MINDA" in comp:
            return "Auto/Truck-Original Eqp IN", "Automobile and Auto Components"
        if sym in BATTERIES_TICKERS or "BATTERY" in comp or "EXIDE" in comp or "AMARA RAJA" in comp:
            return "Auto/Truck-Replace Parts IN", "Automobile and Auto Components"
        if sym in TRACTORS_TICKERS or "TRACTOR" in comp or "ESCORT" in comp:
            return "Machinery-Farm IN", "Automobile and Auto Components"
        if sym in COMMERCIAL_VEH_TICKERS or "ASHOK LEYLAND" in comp or "COMMERCIAL VEHICLE" in comp:
            return "Trucks &amp; Parts-Hvy Duty IN", "Automobile and Auto Components"
        return "Auto Manufacturers IN", "Automobile and Auto Components"

    # 7. Consumer
    if "CONSUMER" in ind or "RETAIL" in ind or "TEXTILES" in ind or "SERVICES" in ind:
        if (
            sym in TEXTILES_TICKERS
            or "TEXTILE" in ind
            or "SPINNING" in comp
            or "WEAVING" in comp
            or "PAGE INDUSTRIES" in comp
            or "WELSPUN LIVING" in comp
            or "RAYMOND" in comp
        ):
            return "Apparel-Clothing Mfg IN", "Textiles"
        if (
            sym in RETAIL_TICKERS
            or "RETAIL" in ind
            or "TRENT" in comp
            or "AVENUE SUPERMARTS" in comp
            or "SHOPPERS STOP" in comp
        ):
            if sym == "TRENT":
                return "Retail-Department Stores IN", "Consumer Services"
            if sym == "DMART":
                return "Retail-Super/Mini Mkts IN", "Consumer Services"
            return "Retail-Specialty IN", "Consumer Services"
        if sym in JEWELLERY_TICKERS or "JEWELLER" in comp or "TITAN" in comp or "GOLD" in comp:
            return "Retail/Whlsle-Jewelry IN", "Consumer Durables"
        if (
            sym in FOOTWEAR_TICKERS
            or "FOOTWEAR" in comp
            or "BATA" in comp
            or "METRO BRAND" in comp
            or "RELAXO" in comp
        ):
            return "Apparel-Shoes &amp; Rel Mfg IN", "Consumer Durables"
        if (
            sym in RESTAURANTS_QSR_TICKERS
            or "RESTAURANT" in comp
            or "FOODWORKS" in comp
            or "DEVYANI" in comp
            or "WESTLIFE" in comp
            or "SAPPHIRE" in comp
        ):
            return "Retail-Restaurants IN", "Consumer Services"

    # Emerging defaults
    if sym in AEROSPACE_DEFENCE_TICKERS or any(
        x in comp for x in ["AEROSPACE", "DEFENCE", "DEFENSE", "DYNAMICS"]
    ):
        return "Aerospace/Defense IN", "Defense"
    if sym in EMS_TICKERS or any(x in comp for x in ["EMS", "DIXON", "KAYNES", "SYRMA", "AVALON"]):
        return "Electronic-Parts IN", "Capital Goods"
    if sym in DATA_CENTERS_TICKERS or "DATA CENTER" in comp or "NETWEB" in comp:
        return "Computer-Hardware/Perip IN", "Information Technology"

    # Defaults
    if "TELECOMMUNICATION" in ind:
        return "Telecom Svcs-Wireless IN", "Telecommunication"
    if "INFORMATION TECHNOLOGY" in ind:
        return "Computer-Tech Services IN", "Information Technology"
    if "CONSTRUCTION MATERIALS" in ind:
        return "Bldg-Cement/Concrt/Ag IN", "Construction Materials"
    if "CONSTRUCTION" in ind:
        return "Bldg-Heavy Construction IN", "Construction"
    if "REALTY" in ind:
        return "Real Estate Dvlpmt/Ops IN", "Realty"
    if "MEDIA" in ind or "PUBLICATION" in ind:
        return "Media-Radio/Tv IN", "Media Entertainment & Publication"

    # Direct raw industry defaults to valid MS industry group names
    raw_ind_map = {
        "FAST MOVING CONSUMER GOODS": ("Food-Packaged IN", "Fast Moving Consumer Goods"),
        "CONSUMER SERVICES": ("Retail-Specialty IN", "Consumer Services"),
        "CONSUMER DURABLES": ("Consumer Prod-Electronic IN", "Consumer Durables"),
        "SERVICES": ("Comml Svcs-Consulting IN", "Services"),
        "DIVERSIFIED": ("Diversified Operations IN", "Diversified"),
        "OIL GAS & CONSUMABLE FUELS": (
            "Oil&amp;Gas-Refining/Mktg IN",
            "Oil Gas & Consumable Fuels",
        ),
        "POWER": ("Utility-Electric Power IN", "Power"),
        "TELECOMMUNICATION": ("Telecom Svcs-Wireless IN", "Telecommunication"),
        "INFORMATION TECHNOLOGY": ("Computer-Tech Services IN", "Information Technology"),
        "METALS & MINING": ("Mining-Metal Ores IN", "Metals & Mining"),
        "CHEMICALS": ("Chemicals-Basic IN", "Specialty Chemicals"),
        "HEALTHCARE": ("Medical-Generic Drugs IN", "Pharma"),
        "AUTOMOBILE AND AUTO COMPONENTS": (
            "Auto/Truck-Original Eqp IN",
            "Automobile and Auto Components",
        ),
        "TEXTILES": ("Apparel-Clothing Mfg IN", "Textiles"),
        "REALTY": ("Real Estate Dvlpmt/Ops IN", "Realty"),
        "MEDIA ENTERTAINMENT & PUBLICATION": (
            "Media-Radio/Tv IN",
            "Media Entertainment & Publication",
        ),
        "CONSTRUCTION MATERIALS": ("Bldg-Cement/Concrt/Ag IN", "Construction Materials"),
        "CONSTRUCTION": ("Bldg-Heavy Construction IN", "Construction"),
    }

    if ind in raw_ind_map:
        return raw_ind_map[ind]

    return "Diversified Operations IN", "Diversified"


# ═══════════════════════════════════════════════════════════════════════
#  MAIN ANALYSIS FUNCTION
# ═══════════════════════════════════════════════════════════════════════
def analyse(symbol, df, info, nse_comp, nse_ind):
    c = df["Close"]
    liq_ok, avg_vol, avg_turn, mktcap = check_liquidity(df, info)
    trend_pts, trend_passed, trend_total = trend_template(df)
    r30, r60, r90, adv_pts, adv_ok = prior_advance(df)
    if not adv_ok:
        return None, "< min advance"
    dist52, prox_pts, h52, l52, prox_ok = high_proximity(df)
    if not prox_ok:
        return None, "too far from 52W high"
    drawdown, dd_pts, dd_ok, btype = consolidation(df)
    if not dd_ok:
        return None, "drawdown too deep"

    vol_contr, vol_pts, dryup = volume_dryup(df)
    atr_ratio, atr_pts, atr_ok = atr_contraction(df)
    tight_pct, tight_pts = tightness(df)
    vcp_bonus, pullbacks = vcp_pullbacks(df)

    pp = pocket_pivot(df)
    pot_bo = potential_bo(df, r60, r90, dist52)
    pb = pull_back_setup(df)

    rs_comp, rs63, rs126, rs252 = rs_proxy_raw(df)

    vcp_s = vcp_score(adv_pts, dd_pts, vol_pts, atr_pts, tight_pts) + vcp_bonus
    vcp_s = min(100, vcp_s)

    stype = "👀 Watch"
    if pb:
        stype = "🧲 Pull Back"
    elif pot_bo:
        stype = "🔮 Potential BO"
    elif drawdown >= -10 and tight_pct <= 8 and dryup:
        stype = "🎯 Mature VCP"
    elif drawdown >= -5:
        stype = "🌱 Early VCP"
    elif atr_ratio < 0.80:
        stype = "📐 Contraction"

    return {
        "symbol": symbol,
        "company": nse_comp,
        "sector": nse_ind,
        "market_cap": mktcap,
        "current": round(c.iloc[-1], 2),
        "h52": h52,
        "l52": l52,
        "avg_vol": avg_vol,
        "avg_turn": avg_turn,
        "r30": r30,
        "r60": r60,
        "r90": r90,
        "dist52": dist52,
        "drawdown": drawdown,
        "base_type": btype,
        "vol_contr": vol_contr,
        "atr_ratio": atr_ratio,
        "tight_pct": tight_pct,
        "trend_passed": f"{trend_passed}/{trend_total}",
        "pullbacks": " → ".join(str(p) + "%" for p in pullbacks) or "—",
        "pocket_pivot": "✅ YES" if pp else "—",
        "pot_bo": "✅ YES" if pot_bo else "—",
        "pull_back": "✅ YES" if pb else "—",
        "vcp_score": vcp_s,
        "lead_score": 0,
        "rs_score": 0,
        "final_score": 0,
        "grade": "—",
        "setup": stype,
        "adv_pts": adv_pts,
        "prox_pts": prox_pts,
        "trend_pts": trend_pts,
        "avg_turn_liq": avg_turn,
        "_rs_composite": rs_comp,
    }, None


# ═══════════════════════════════════════════════════════════════════════
#  HTML & JS GENERATION
# ═══════════════════════════════════════════════════════════════════════

UI_CSS = r"""
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#060d18;color:#e2e8f5;font-family:system-ui,-apple-system,sans-serif;min-height:100vh}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-thumb{background:#2d3f5a;border-radius:3px}
::-webkit-scrollbar-track{background:#0d1929}
.tab{display:none}.tab.active{display:block}
.tab-btn{background:none;border:none;border-bottom:2px solid transparent;color:#64748b;
         font-size:12px;font-weight:700;padding:10px 18px;cursor:pointer;transition:color .15s}
.tab-btn:hover{color:#94a3b8}
.tab-btn.active{color:#2dd4bf;border-bottom-color:#2dd4bf}
.sort-arrow{color:#2d3f5a;font-size:9px;margin-left:3px}
th:hover{background:#0d1525 !important;color:#e2e8f5 !important}
th:hover .sort-arrow{color:#2dd4bf}
.search-box{background:#0d1929; border:1px solid #1e2d45; color:#e2e8f5; padding:8px 14px;
            border-radius:6px; font-size:12px; outline:none; width:100%; min-width:280px; transition:border-color 0.2s;}
.search-box:focus{border-color:#2dd4bf;}
.search-box::placeholder{color:#475569;}
</style>
"""

UI_SCRIPT = r"""
<script>
function filterTable() {
  var input = document.getElementById("searchBox").value.toLowerCase();
  var activeTab = document.querySelector('.tab.active');
  if (!activeTab) return;
  var rows = activeTab.querySelectorAll('tbody tr');
  rows.forEach(function(row) {
    if(row.cells.length >= 3) {
      var text = row.cells[0].textContent + " " + row.cells[1].textContent + " " + row.cells[2].textContent;
      row.style.display = text.toLowerCase().indexOf(input) > -1 ? "" : "none";
    }
  });
}

function switchTab(name, btn) {
  document.querySelectorAll('.tab').forEach(function(t){ t.classList.remove('active'); });
  document.querySelectorAll('.tab-btn').forEach(function(b){ b.classList.remove('active'); });
  var el = document.getElementById('tab-' + name);
  if (el) el.classList.add('active');
  btn.classList.add('active');
  filterTable();
}

function switchBreadthView(view, btn) {
  document.getElementById('breadth-view-sec').style.display = (view === 'sec') ? '' : 'none';
  document.getElementById('breadth-view-ind').style.display = (view === 'ind') ? '' : 'none';
  document.querySelectorAll('.breadth-view-btn').forEach(function(b){
    b.classList.remove('active');
    b.style.background = '#0d1929'; b.style.color = '#64748b'; b.style.borderColor = '#1e2d45';
  });
  btn.classList.add('active');
  btn.style.background = 'rgba(45,212,191,.1)'; btn.style.color = '#2dd4bf'; btn.style.borderColor = 'rgba(45,212,191,.3)';
}

var _ss = {};
function sortTable(th) {
  var tbl  = th.closest('table');
  var tb   = tbl.querySelector('tbody');
  var col  = parseInt(th.getAttribute('data-col'));
  var key  = tbl.id + '_' + col;
  var next = (_ss[key] === 'asc') ? 'desc' : 'asc';
  _ss[key] = next;
  tbl.querySelectorAll('th .sort-arrow').forEach(function(a){ a.textContent = '\u21c5'; });
  th.querySelector('.sort-arrow').textContent = next === 'asc' ? '\u25b2' : '\u25bc';
  var rows = Array.from(tb.querySelectorAll('tr'));
  var clean = function(v) { return v.replace(/[^0-9.+\-]/g,'').trim(); };
  rows.sort(function(a,b) {
    var ac = a.querySelectorAll('td')[col], bc = b.querySelectorAll('td')[col];
    if (!ac||!bc) return 0;
    var av = ac.textContent.trim(), bv = bc.textContent.trim();
    var an = parseFloat(clean(av)), bn = parseFloat(clean(bv));
    var cmp = (!isNaN(an)&&!isNaN(bn)) ? an-bn : av.localeCompare(bv,'en',{numeric:true});
    return next==='asc' ? cmp : -cmp;
  });
  rows.forEach(function(r,i){ r.style.background=i%2===0?'#0d1929':'#0f1c30'; tb.appendChild(r); });
}

document.addEventListener('click', function(e) {
  var btn = e.target.closest('.wl-btn');
  if (!btn) return;
  var syms  = JSON.parse(btn.getAttribute('data-syms') || '[]');
  var lines = [];
  for (var i=0; i<syms.length; i+=10) {
    lines.push(syms.slice(i,i+10).map(function(s){ return 'NSE:'+s; }).join(', '));
  }
  showWLModal(lines.join(',\n'), syms.length);
});

function showWLModal(content, count) {
  var old = document.getElementById('wl-modal'); if (old) old.remove();
  var m = document.createElement('div');
  m.id = 'wl-modal';
  m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  m.innerHTML = (
    '<div style="background:#0d1929;border:1px solid #2d3f5a;border-radius:10px;width:100%;max-width:700px;max-height:82vh;display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,.9)">'
    +'<div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #1e2d45">'
    +'<div><div style="font-size:14px;font-weight:800;color:#2dd4bf">&#128203; TradingView Watchlist Export</div>'
    +'<div style="font-size:11px;color:#64748b;margin-top:2px">'+count+' symbols &middot; NSE: prefix added &middot; 10 per line</div></div>'
    +'<button onclick="document.getElementById(\'wl-modal\').remove()" style="background:none;border:none;color:#64748b;font-size:22px;cursor:pointer;padding:2px 8px">&times;</button></div>'
    +'<div style="padding:14px 20px;flex:1;overflow-y:auto">'
    +'<textarea id="wl-txt" readonly style="width:100%;height:250px;background:#060d18;border:1px solid #1e2d45;'
    +'color:#a5d6e8;font-family:Consolas,monospace;font-size:12px;line-height:1.9;padding:12px;border-radius:6px;resize:vertical;outline:none">'+content+'</textarea></div>'
    +'<div style="padding:14px 20px;border-top:1px solid #1e2d45;display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
    +'<button onclick="cpWL()" style="background:#2dd4bf;color:#060d18;border:none;border-radius:5px;padding:9px 22px;font-size:12px;font-weight:800;cursor:pointer">&#8680; Copy to Clipboard</button>'
    +'<button onclick="dlWL()" style="background:rgba(45,212,191,.1);color:#2dd4bf;border:1px solid rgba(45,212,191,.3);border-radius:5px;padding:9px 16px;font-size:12px;font-weight:700;cursor:pointer">&#8595; Download .txt</button>'
    +'<span id="wl-msg" style="font-size:12px;color:#4ade80;font-weight:700;opacity:0;transition:opacity .3s"></span></div>'
    +'</div>'
  );
  document.body.appendChild(m);
  m.addEventListener('click', function(e){ if(e.target===m) m.remove(); });
}
function cpWL(){
  var ta=document.getElementById('wl-txt');
  ta.select(); ta.setSelectionRange(0,99999);
  try{ navigator.clipboard.writeText(ta.value); }catch(e){ document.execCommand('copy'); }
  var msg=document.getElementById('wl-msg');
  msg.textContent='\u2705 Copied!'; msg.style.opacity='1';
  setTimeout(function(){ msg.style.opacity='0'; },2500);
}
function dlWL(){
  var c=document.getElementById('wl-txt').value;
  var a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([c],{type:'text/plain'}));
  a.download='vcp_watchlist.txt'; a.click();
}
</script>
"""


def grade_color(g):
    return {
        "A+": "#2dd4bf",
        "A": "#4ade80",
        "B": "#fbbf24",
        "C": "#fb923c",
        "REJECT": "#f87171",
    }.get(g, "#94a3b8")


def build_table_rows(stocks, bg1="#0d1929", bg2="#0f1c30"):
    rows = []
    for i, r in enumerate(stocks):
        bg = bg1 if i % 2 == 0 else bg2
        gc = grade_color(r["grade"])
        r30c = "#4ade80" if r["r30"] >= 30 else "#fbbf24" if r["r30"] >= 15 else "#f87171"
        r60c = "#4ade80" if r["r60"] >= 40 else "#fbbf24" if r["r60"] >= 20 else "#f87171"
        r90c = "#4ade80" if r["r90"] >= 50 else "#fbbf24" if r["r90"] >= 30 else "#f87171"
        dc = "#4ade80" if r["drawdown"] >= -5 else "#fbbf24" if r["drawdown"] >= -15 else "#f87171"
        vc = "#4ade80" if r["vol_contr"] <= -20 else "#fbbf24" if r["vol_contr"] < 0 else "#f87171"
        ac = (
            "#4ade80"
            if r["atr_ratio"] < 0.75
            else "#fbbf24"
            if r["atr_ratio"] < 0.85
            else "#f87171"
        )
        tc = "#4ade80" if r["tight_pct"] <= 8 else "#fbbf24" if r["tight_pct"] <= 12 else "#f87171"

        pp = '<span style="color:#2dd4bf">✅</span>' if "✅" in r.get("pocket_pivot", "") else "—"
        potbo = '<span style="color:#a855f7">✅</span>' if "✅" in r.get("pot_bo", "") else "—"
        pb = '<span style="color:#f43f5e">✅</span>' if "✅" in r.get("pull_back", "") else "—"

        tv_link = f"{CFG['tv_chart_url']}?symbol=NSE:{r['symbol']}"

        rows.append(f"""<tr style="background:{bg};border-bottom:1px solid #1e2d45">
  <td style="padding:9px 12px;font-weight:800;font-size:12px;white-space:nowrap">
    <div style="display:flex;align-items:center;gap:8px">
        <a href="https://marketsmithindia.com/mstool/eval/{r["symbol"].lower()}/evaluation.jsp#/"
           target="_blank"
           style="color:#2dd4bf;text-decoration:none;border-bottom:1px dashed rgba(45,212,191,.4)"
           title="Open {r["symbol"]} on MarketSmith India">{r["symbol"]} ↗</a>
        <a href="{tv_link}" target="_blank"
           style="background:#1e2d45;color:#94a3b8;font-size:9px;padding:2px 5px;border-radius:4px;text-decoration:none;font-weight:bold;transition:all 0.2s"
           onmouseover="this.style.background='#2962ff';this.style.color='#fff'"
           onmouseout="this.style.background='#1e2d45';this.style.color='#94a3b8'"
           title="Open {r["symbol"]} in TradingView">TV</a>
    </div>
  </td>
  <td style="padding:9px 8px;font-size:10px;color:#7cb4e0;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{r["company"]}</td>
  <td style="padding:9px 8px;font-size:10px;color:#64748b;white-space:nowrap">{r["sector"]}</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:#94a3b8">{r["market_cap"]:,}</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:12px;font-weight:700;color:#e2e8f5">₹{r["current"]:,.2f}</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:{r30c}">{r["r30"]:+.1f}%</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:{r60c}">{r["r60"]:+.1f}%</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:{r90c}">{r["r90"]:+.1f}%</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:#60a5fa">{r["dist52"]:+.1f}%</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:{dc}">{r["drawdown"]:+.1f}%</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:{vc}">{r["vol_contr"]:+.1f}%</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:{ac}">{r["atr_ratio"]:.3f}</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:{tc}">{r["tight_pct"]:.1f}%</td>
  <td style="padding:9px 8px;font-size:11px;color:#a78bfa;white-space:nowrap">{r["pullbacks"]}</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:#fb923c">{r["rs_score"]:.0f}</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:#60a5fa">{r["vcp_score"]:.0f}</td>
  <td style="padding:9px 8px;font-family:monospace;font-size:11px;color:#a78bfa">{r["lead_score"]:.0f}</td>
  <td style="padding:9px 12px;text-align:center">
    <span style="font-size:18px;font-weight:900;color:{gc}">{r["final_score"]:.0f}</span>
  </td>
  <td style="padding:9px 8px;text-align:center">
    <span style="background:{gc}22;color:{gc};padding:2px 8px;border-radius:12px;
                 font-size:11px;font-weight:800;border:1px solid {gc}44">{r["grade"]}</span>
  </td>
  <td style="padding:9px 8px;font-size:11px;white-space:nowrap">{r["setup"]}</td>
  <td style="padding:9px 8px;text-align:center">{potbo}</td>
  <td style="padding:9px 8px;text-align:center">{pb}</td>
  <td style="padding:9px 8px;text-align:center">{pp}</td>
</tr>""")
    return "\n".join(rows)


def TH(t, i):
    return (
        f'<th data-col="{i}" onclick="sortTable(this)" '
        f'style="padding:8px 8px;text-align:left;font-size:9px;color:#64748b;'
        f"letter-spacing:.7px;white-space:nowrap;background:#0a1220;"
        f'cursor:pointer;user-select:none" '
        f"title=\"Click to sort\">{t} <span class='sort-arrow'>⇅</span></th>"
    )


HEADERS = "".join(
    TH(h, i)
    for i, h in enumerate(
        [
            "SYMBOL",
            "COMPANY",
            "NSE THEME/IND.",
            "MKTCAP(Cr)",
            "PRICE",
            "30D%",
            "60D%",
            "90D%",
            "DIST 52W",
            "DRAWDOWN",
            "VOL CONTR",
            "ATR RATIO",
            "TIGHTNESS",
            "VCP PULLS",
            "RS SCORE",
            "VCP SCORE",
            "LEAD SCORE",
            "FINAL",
            "GRADE",
            "SETUP",
            "POTENTIAL BO",
            "PULL BACK",
            "PP",
        ]
    )
)


def generate_html(results, scan_time, total_scanned, errors, rejects, sector_stats, industry_stats):
    import json as _json

    elite = [r for r in results if r["grade"] in ("A+", "A")][:20]
    potbo_list = [r for r in results if r.get("pot_bo") and "YES" in r["pot_bo"]][:20]
    pb_list = [r for r in results if r.get("pull_back") and "YES" in r["pull_back"]][:20]
    pp_list = [r for r in results if r["pocket_pivot"] and "YES" in r["pocket_pivot"]][:20]
    watch = [r for r in results if r["grade"] == "B"][:20]
    emerge = [r for r in results if r["grade"] == "C"][:20]

    def card(lbl, val, clr, sub):
        return (
            f'<div style="background:#0d1929;border:1px solid #1e2d45;border-radius:6px;padding:14px 16px">'
            f'<div style="font-size:9px;color:#64748b;letter-spacing:.8px;text-transform:uppercase;margin-bottom:6px">{lbl}</div>'
            f'<div style="font-size:26px;font-weight:900;color:{clr}">{val}</div>'
            f'<div style="font-size:10px;color:#64748b;margin-top:2px">{sub}</div></div>'
        )

    cards = (
        card("Elite (A+/A)", len(elite), "#2dd4bf", "Score &ge; 80")
        + card("Potential BO", len(potbo_list), "#a855f7", "Resting near pivot")
        + card("Pull Backs", len(pb_list), "#f43f5e", "Retesting support")
        + card("Pocket Pivots", len(pp_list), "#fbbf24", "O'Neil confirmed")
    )

    # Generate Sector Health Table
    sec_rows = []
    sorted_secs = sorted(sector_stats.items(), key=lambda x: (-x[1]["vcp"], -x[1]["total"]))
    for sec, st in sorted_secs:
        if st["total"] == 0:
            continue
        tot, vcp = st["total"], st["vcp"]
        p20 = int((st["a20"] / tot) * 100)
        p50 = int((st["a50"] / tot) * 100)
        p200 = int((st["a200"] / tot) * 100)

        c20 = "#4ade80" if p20 >= 60 else "#fbbf24" if p20 >= 40 else "#f87171"
        c50 = "#4ade80" if p50 >= 60 else "#fbbf24" if p50 >= 40 else "#f87171"
        c200 = "#4ade80" if p200 >= 60 else "#fbbf24" if p200 >= 40 else "#f87171"
        vcp_c = "#2dd4bf" if vcp > 0 else "#64748b"

        sec_rows.append(f"""<tr style="border-bottom:1px solid #1e2d45;background:#0d1929">
            <td style="padding:6px 10px;font-size:11px;font-weight:700;color:#e2e8f5;white-space:nowrap;">{sec}</td>
            <td style="padding:6px 10px;font-size:11px;text-align:center;color:#94a3b8">{tot}</td>
            <td style="padding:6px 10px;font-size:12px;font-weight:800;text-align:center;color:{vcp_c}">{vcp}</td>
            <td style="padding:6px 10px;font-size:11px;text-align:center;color:{c20}">{p20}%</td>
            <td style="padding:6px 10px;font-size:11px;text-align:center;color:{c50}">{p50}%</td>
            <td style="padding:6px 10px;font-size:11px;text-align:center;color:{c200}">{p200}%</td>
        </tr>""")

    sec_table = f"""<div style="background:#0d1929;border:1px solid #1e2d45;border-radius:6px;overflow:hidden;height:100%">
        <div style="padding:10px 16px;background:#0a1220;border-bottom:1px solid #1e2d45;font-size:11px;font-weight:800;color:#2dd4bf;letter-spacing:1px;text-transform:uppercase">
            📊 Thematic Breadth & Health
        </div>
        <div style="max-height:220px;overflow-y:auto;overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;text-align:left;white-space:nowrap;">
                <thead style="position:sticky;top:0;background:#0f1c30;box-shadow:0 1px 0 #1e2d45">
                    <tr>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b">NSE THEME/INDUSTRY</th>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b;text-align:center">UNIVERSE</th>
                        <th style="padding:8px 10px;font-size:9px;color:#2dd4bf;text-align:center">VCP CANDIDATES</th>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b;text-align:center">% > 20 EMA</th>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b;text-align:center">% > 50 SMA</th>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b;text-align:center">% > 200 SMA</th>
                    </tr>
                </thead>
                <tbody>{"".join(sec_rows)}</tbody>
            </table>
        </div>
    </div>"""

    # Generate Industry Group Health Table (granular sub-split of the sectors above)
    ind_rows = []
    sorted_inds = sorted(industry_stats.items(), key=lambda x: (-x[1]["vcp"], -x[1]["total"]))
    for ind, st in sorted_inds:
        if st["total"] == 0:
            continue
        tot, vcp = st["total"], st["vcp"]
        p20 = int((st["a20"] / tot) * 100)
        p50 = int((st["a50"] / tot) * 100)
        p200 = int((st["a200"] / tot) * 100)

        c20 = "#4ade80" if p20 >= 60 else "#fbbf24" if p20 >= 40 else "#f87171"
        c50 = "#4ade80" if p50 >= 60 else "#fbbf24" if p50 >= 40 else "#f87171"
        c200 = "#4ade80" if p200 >= 60 else "#fbbf24" if p200 >= 40 else "#f87171"
        vcp_c = "#2dd4bf" if vcp > 0 else "#64748b"
        parent = st.get("parent", "")

        ind_rows.append(f"""<tr style="border-bottom:1px solid #1e2d45;background:#0d1929">
            <td style="padding:6px 10px;font-size:11px;font-weight:700;color:#e2e8f5;white-space:nowrap;">{ind}<span style="font-size:9px;font-weight:500;color:#475569;margin-left:6px">{parent}</span></td>
            <td style="padding:6px 10px;font-size:11px;text-align:center;color:#94a3b8">{tot}</td>
            <td style="padding:6px 10px;font-size:12px;font-weight:800;text-align:center;color:{vcp_c}">{vcp}</td>
            <td style="padding:6px 10px;font-size:11px;text-align:center;color:{c20}">{p20}%</td>
            <td style="padding:6px 10px;font-size:11px;text-align:center;color:{c50}">{p50}%</td>
            <td style="padding:6px 10px;font-size:11px;text-align:center;color:{c200}">{p200}%</td>
        </tr>""")

    ind_table = f"""<div style="background:#0d1929;border:1px solid #1e2d45;border-radius:6px;overflow:hidden;height:100%">
        <div style="padding:10px 16px;background:#0a1220;border-bottom:1px solid #1e2d45;font-size:11px;font-weight:800;color:#2dd4bf;letter-spacing:1px;text-transform:uppercase">
            🏷️ Industry Group Breadth & Health
        </div>
        <div style="max-height:220px;overflow-y:auto;overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;text-align:left;white-space:nowrap;">
                <thead style="position:sticky;top:0;background:#0f1c30;box-shadow:0 1px 0 #1e2d45">
                    <tr>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b">INDUSTRY GROUP <span style="color:#334155">(parent sector)</span></th>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b;text-align:center">UNIVERSE</th>
                        <th style="padding:8px 10px;font-size:9px;color:#2dd4bf;text-align:center">VCP CANDIDATES</th>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b;text-align:center">% > 20 EMA</th>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b;text-align:center">% > 50 SMA</th>
                        <th style="padding:8px 10px;font-size:9px;color:#64748b;text-align:center">% > 200 SMA</th>
                    </tr>
                </thead>
                <tbody>{"".join(ind_rows)}</tbody>
            </table>
        </div>
    </div>"""

    breadth_panel = f"""<div style="background:transparent;height:100%">
        <div style="display:flex;gap:4px;margin-bottom:6px">
            <button class="breadth-view-btn active" onclick="switchBreadthView('sec',this)"
                style="background:rgba(45,212,191,.1);color:#2dd4bf;border:1px solid rgba(45,212,191,.3);border-radius:5px 5px 0 0;padding:5px 14px;font-size:10px;font-weight:700;cursor:pointer">
                📊 Sectors &middot; {len([s for s in sector_stats.values() if s["total"]])}
            </button>
            <button class="breadth-view-btn" onclick="switchBreadthView('ind',this)"
                style="background:#0d1929;color:#64748b;border:1px solid #1e2d45;border-radius:5px 5px 0 0;padding:5px 14px;font-size:10px;font-weight:700;cursor:pointer">
                🏷️ Industries &middot; {len([s for s in industry_stats.values() if s["total"]])}
            </button>
        </div>
        <div id="breadth-view-sec">{sec_table}</div>
        <div id="breadth-view-ind" style="display:none">{ind_table}</div>
    </div>"""

    def tab_section(title, color, stocks, tid):
        if not stocks:
            return '<div style="color:#475569;text-align:center;padding:48px;font-size:13px">No stocks in this category.</div>'
        rows = build_table_rows(stocks)
        syms = _json.dumps([r["symbol"] for r in stocks])
        safe_title = "".join(c for c in title if ord(c) < 128)
        return (
            f'<div style="margin-bottom:36px">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px">'
            f'<h2 style="color:{color};font-size:13px;font-weight:800;letter-spacing:1px;text-transform:uppercase;'
            f'margin:0;padding:10px 16px;background:rgba(255,255,255,.03);border-left:3px solid {color};border-radius:0 4px 4px 0">'
            f"{title} &mdash; {len(stocks)} stocks</h2>"
            f'<button class="wl-btn" data-syms=\'{syms}\' data-title="{safe_title}" '
            f'style="background:rgba(45,212,191,.1);color:#2dd4bf;border:1px solid rgba(45,212,191,.3);'
            f'border-radius:5px;padding:7px 16px;font-size:11px;font-weight:700;cursor:pointer;white-space:nowrap">'
            f"&#128203; Export TradingView Watchlist</button></div>"
            f'<div style="overflow-x:auto;border:1px solid #1e2d45;border-radius:6px">'
            f'<table id="tbl-{tid}" style="width:100%;border-collapse:collapse;font-family:system-ui;min-width:1450px">'
            f"<thead><tr>{HEADERS}</tr></thead><tbody>{rows}</tbody></table></div></div>"
        )

    s_elite = tab_section("Elite VCP Candidates (A+ / A)", "#2dd4bf", elite, "elite")
    s_potbo = tab_section("Potential Breakouts", "#a855f7", potbo_list, "potbo")
    s_pb = tab_section("Pull Back Setups", "#f43f5e", pb_list, "pb")
    s_pp = tab_section("Pocket Pivot Candidates", "#fbbf24", pp_list, "pp")
    s_watch = tab_section("Watchlist (Grade B)", "#a78bfa", watch, "watch")
    s_emerge = tab_section("Emerging (Grade C)", "#fb923c", emerge, "emerge")
    s_all = tab_section("All Qualified Stocks", "#60a5fa", results, "all")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VCP Scanner &mdash; {scan_time}</title>
{UI_CSS}
</head>
<body>
<div style="max-width:1700px;margin:0 auto;padding:24px">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;
      margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid #1e2d45;flex-wrap:wrap;gap:12px">
    <div>
      <h1 style="font-size:26px;font-weight:900;color:#2dd4bf;letter-spacing:-0.5px">&#128225; VCP SCANNER</h1>
      <p style="font-size:12px;color:#64748b;margin-top:4px">Minervini Trend Template &middot; Stage-2 &middot; VCP &middot; Pocket Pivot &middot; Potential BO</p>
    </div>
    <div style="text-align:right;font-size:11px;color:#64748b;line-height:1.9">
      <div>Run: <b style="color:#94a3b8">{scan_time}</b></div>
      <div>Qualified:<b style="color:#4ade80"> {len(results)}</b> &nbsp;|&nbsp; Rejected:<b style="color:#f87171"> {rejects}</b> &nbsp;|&nbsp; Errors:<b style="color:#fb923c"> {errors}</b></div>
      <div style="color:#334155">Data: Yahoo Finance + NSE Smart Split</div>
    </div>
  </div>

  <div style="display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap;align-items:stretch">
    <div style="flex:1;min-width:300px;display:grid;grid-template-columns:repeat(2,1fr);gap:12px;align-content:start;">
        {cards}
    </div>
    <div style="flex:2;min-width:280px;width:100%;">
        {breadth_panel}
    </div>
  </div>

  <div style="border-bottom:1px solid #1e2d45;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;padding-bottom:8px">
    <div style="display:flex;gap:0;flex-wrap:wrap">
        <button class="tab-btn active" onclick="switchTab('elite',this)">&#127942; Elite (A+/A)</button>
        <button class="tab-btn" onclick="switchTab('potbo',this)">&#128302; Potential BO</button>
        <button class="tab-btn" onclick="switchTab('pb',this)">&#129682; Pull Backs</button>
        <button class="tab-btn" onclick="switchTab('pp',this)">&#9889; Pocket Pivots</button>
        <button class="tab-btn" onclick="switchTab('watch',this)">&#128064; Watchlist (B)</button>
        <button class="tab-btn" onclick="switchTab('emerge',this)">&#127807; Emerging (C)</button>
        <button class="tab-btn" onclick="switchTab('all',this)">&#128203; All Results</button>
    </div>
    <div>
        <input type="text" id="searchBox" class="search-box" placeholder="&#128269; Filter Symbol, Company, Theme..." onkeyup="filterTable()">
    </div>
  </div>

  <div id="tab-elite"  class="tab active">{s_elite}</div>
  <div id="tab-potbo"  class="tab">{s_potbo}</div>
  <div id="tab-pb"     class="tab">{s_pb}</div>
  <div id="tab-pp"     class="tab">{s_pp}</div>
  <div id="tab-watch"  class="tab">{s_watch}</div>
  <div id="tab-emerge" class="tab">{s_emerge}</div>
  <div id="tab-all"    class="tab">{s_all}</div>

  <div style="margin-top:24px;padding-top:16px;border-top:1px solid #1e2d45;font-size:10px;color:#475569;text-align:center;line-height:2">
    VCP Score (60%) = Advance + Drawdown + Volume + ATR + Tightness &nbsp;|&nbsp; Leadership (40%) = 52W Proximity + Trend + RS Proxy + Liquidity<br>
    Yahoo Finance (15-min delayed) &middot; Run weekly after market close for Monday watchlist<br>
    <b>Not a buy recommendation. Always verify on TradingView + MarketSmith before acting.</b>
  </div>
</div>
{UI_SCRIPT}
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════
def main():
    interrupter = GracefulInterruptHandler()

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  VCP SCANNER  v3.2  —  Minervini · O'Neil · Stage-2        ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    # 1. Load the NSE CSV dynamically
    try:
        dir_path = Path(__file__).resolve().parent
        csv_path1 = dir_path / "ind_nifty500list.csv"
        csv_path2 = dir_path / "ind_niftymidsmallcap400list.csv"

        nse_df1 = pd.read_csv(csv_path1)
        nse_df2 = pd.read_csv(csv_path2)

        # Clean symbols and combine
        nse_df1["Symbol"] = nse_df1["Symbol"].astype(str).str.strip()
        nse_df2["Symbol"] = nse_df2["Symbol"].astype(str).str.strip()

        nse_df = pd.concat([nse_df1, nse_df2], ignore_index=True)
        nse_df = nse_df.drop_duplicates(subset=["Symbol"])

        nse_map = nse_df.set_index("Symbol").to_dict("index")
        symbols_to_scan = list(nse_map.keys())
        print(f"✅ Successfully loaded {len(nse_df1)} symbols from ind_nifty500list.csv")
        print(f"✅ Successfully loaded {len(nse_df2)} symbols from ind_niftymidsmallcap400list.csv")
        print(f"✅ Merged unique universe: {len(symbols_to_scan)} symbols to scan")
    except Exception as e:
        print(
            "❌ Error loading stock list CSVs. Ensure ind_nifty500list.csv and ind_niftymidsmallcap400list.csv are placed in the exact same folder as this script."
        )
        print(f"Details: {e}")
        sys.exit(1)

    print("\n💡 TIP: Press Ctrl+C at any time to instantly stop scanning and generate")
    print("the output HTML files for the stocks processed up to that point.\n")

    total = len(symbols_to_scan)
    results = []
    errors = 0
    rejects = 0
    scan_time = datetime.now().strftime("%d %b %Y  %I:%M %p")

    sector_stats = {}
    industry_stats = {}

    print(f"⚡ Bulk downloading price data for {total} NSE stocks in parallel via Yahoo Finance...")
    clean_symbols = [
        s for s in symbols_to_scan if isinstance(s, str) and s.strip() and not s.startswith("DUMMY")
    ]
    yf_tickers = [s + ".NS" for s in clean_symbols]
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=400)

    global BULK_STOCK_DATA
    BULK_STOCK_DATA = {}

    try:
        chunk_size = 150
        for c_idx in range(0, len(yf_tickers), chunk_size):
            chunk_tickers = yf_tickers[c_idx : c_idx + chunk_size]
            b_df = yf.download(
                chunk_tickers,
                start=start_dt,
                end=end_dt,
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if b_df is not None and not b_df.empty:
                if isinstance(b_df.columns, pd.MultiIndex):
                    for t_str in chunk_tickers:
                        if t_str in b_df.columns.levels[0]:
                            s_df = b_df[t_str].dropna(subset=["Close"])
                            if len(s_df) >= 252:
                                sym_clean = t_str.replace(".NS", "")
                                BULK_STOCK_DATA[sym_clean] = s_df[
                                    ["Open", "High", "Low", "Close", "Volume"]
                                ].dropna()
                else:
                    if len(b_df) >= 252:
                        sym_clean = chunk_tickers[0].replace(".NS", "")
                        BULK_STOCK_DATA[sym_clean] = b_df[
                            ["Open", "High", "Low", "Close", "Volume"]
                        ].dropna()
        print(f"✅ Bulk download complete! Cached {len(BULK_STOCK_DATA)} stocks in memory.\n")
    except Exception as b_err:
        print(f"⚠️ Bulk download warning: {b_err}. Falling back to individual fetching.\n")

    print(f"Scanning {total} NSE stocks via Yahoo Finance...\n")

    for i, sym in enumerate(symbols_to_scan, 1):
        if interrupter.interrupted:
            print(
                f"\nProceeding to generate report with the {len(results)} valid stocks found so far...\n"
            )
            break

        try:
            # Look up specific NSE data from the CSV map
            nse_info = nse_map.get(sym, {})
            nse_ind = nse_info.get("Industry", "Unknown")
            nse_ind_raw = nse_ind  # preserved BEFORE the theme overrides below —
            # get_industry_group()'s substring matching is
            # built against NSE's raw taxonomy, not our
            # display-friendly Sector-tab labels.
            nse_comp = nse_info.get("Company Name", sym)

            df, info = fetch_data(sym)
            if df is None:
                print(f"  [{i:3d}/{total}] {sym:<15} — skip (no data)")
                continue

            # Get the exact Industry Group and Parent Sector from CSV/Heuristics
            industry_group, parent_sector = get_industry_group(sym, nse_comp, nse_ind_raw)

            # Apply custom theme overrides
            comp_lower = nse_comp.lower()
            railway_tickers = {
                "IRFC",
                "IRCTC",
                "RVNL",
                "IRCON",
                "RITES",
                "TITAGARH",
                "TEXMACO",
                "RAILTEL",
                "JWL",
            }
            if sym in railway_tickers or "railway" in comp_lower:
                industry_group, parent_sector = "Railways", "Railways"
            elif sym in {"MAZDOCK", "COCHINSHIP", "GRSE"}:
                parent_sector = "Defense"

            # Ensure sector and parent sector are exactly aligned
            nse_ind = parent_sector

            if nse_ind not in sector_stats:
                sector_stats[nse_ind] = {"total": 0, "vcp": 0, "a20": 0, "a50": 0, "a200": 0}
            if industry_group not in industry_stats:
                industry_stats[industry_group] = {
                    "total": 0,
                    "vcp": 0,
                    "a20": 0,
                    "a50": 0,
                    "a200": 0,
                    "parent": parent_sector,
                }

            # Safely capture Universe MAs before filtering
            c = df["Close"]
            c0 = c.iloc[-1]
            e20 = ema(c, 20).iloc[-1]
            s50 = sma(c, 50).iloc[-1]
            s200 = sma(c, 200).iloc[-1]

            sector_stats[nse_ind]["total"] += 1
            if c0 > e20:
                sector_stats[nse_ind]["a20"] += 1
            if c0 > s50:
                sector_stats[nse_ind]["a50"] += 1
            if c0 > s200:
                sector_stats[nse_ind]["a200"] += 1

            industry_stats[industry_group]["total"] += 1
            if c0 > e20:
                industry_stats[industry_group]["a20"] += 1
            if c0 > s50:
                industry_stats[industry_group]["a50"] += 1
            if c0 > s200:
                industry_stats[industry_group]["a200"] += 1

            # Pass SMART NSE mappings directly to the analysis engine
            result, reason = analyse(sym, df, info, nse_comp, nse_ind)

            if result is None:
                rejects += 1
                print(f"  [{i:3d}/{total}] {sym:<15} — ✗ {reason}")
                continue

            result["industry_group"] = industry_group
            result["parent_sector"] = parent_sector
            results.append(result)
            sector_stats[nse_ind]["vcp"] += 1
            industry_stats[industry_group]["vcp"] += 1

            print(
                f"  [{i:3d}/{total}] {sym:<15} — vcp:{result['vcp_score']:3.0f}"
                f"  adv:{result['r90']:+.0f}%"
                f"  dd:{result['drawdown']:+.0f}%"
                f"  atr:{result['atr_ratio']:.2f}"
                f"  tight:{result['tight_pct']:.1f}%"
                f"  {result['setup']}"
            )

            if sym not in BULK_STOCK_DATA:
                time.sleep(CFG["delay_between_stocks"])

        except Exception as e:
            errors += 1
            print(f"  [{i:3d}/{total}] {sym:<15} — ERROR: {e}")
            continue

    if not results:
        print("\n❌ No stocks were fully processed to generate a report. Exiting.")
        sys.exit(0)

    print("\n═══ Computing RS Scores & Final Rankings ═══")

    results = compute_rs_scores(results)

    for r in results:
        r["rs_score"] = r.get("rs_score", 0)
        r["lead_score"] = leadership_score(
            r["prox_pts"], r["trend_pts"], r["rs_score"], r["avg_turn_liq"]
        )
        r["final_score"] = composite_score(r["vcp_score"], r["lead_score"])
        r["grade"] = grade(r["final_score"])

    results.sort(key=lambda x: -x["final_score"])

    elite = [r for r in results if r["grade"] in ("A+", "A")]
    pot_bos = [r for r in results if "✅" in r.get("pot_bo", "")]

    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  SCAN COMPLETE                                               ║")
    print(
        f"║  Qualified:{len(results):4d}  |  Elite:{len(elite):3d}  |  Rejected:{rejects:4d}  |  Errors:{errors:3d}  ║"
    )
    print("╚══════════════════════════════════════════════════════════════╝\n")

    if elite:
        print("🏆 ELITE (A+/A):")
        for r in elite[:20]:
            print(
                f"   {r['symbol']:<14} score:{r['final_score']:5.1f}  "
                f"grade:{r['grade']}  vcp:{r['vcp_score']:4.0f}  "
                f"rs:{r['rs_score']:4.0f}  {r['setup']}"
            )

    if pot_bos:
        print(f"\n🔮 POTENTIAL BREAKOUTS ({len(pot_bos)}):")
        for r in pot_bos[:10]:
            print(f"   {r['symbol']:<14} score:{r['final_score']:5.1f}")

    out_dir = Path(__file__).resolve().parent
    html_out = out_dir / "vcp_scanner_results.html"

    print("\nGenerating HTML report...")
    html = generate_html(results, scan_time, total, errors, rejects, sector_stats, industry_stats)
    html_out.write_text(html, encoding="utf-8")
    print(f"✅ HTML saved: {html_out}")

    # Output sector_breadth.json and sector_stocks.json
    print("Generating JSON sidecars...")
    import json

    # 1. sector_breadth.json
    sectors_arr = []
    for sec, st in sector_stats.items():
        if st["total"] == 0:
            continue
        sectors_arr.append(
            {
                "sector": sec,
                "universe": st["total"],
                "vcp_count": st["vcp"],
                "a20_pct": int((st["a20"] / st["total"]) * 100),
                "a50_pct": int((st["a50"] / st["total"]) * 100),
                "a200_pct": int((st["a200"] / st["total"]) * 100),
            }
        )

    industries_arr = []
    for ind, st in industry_stats.items():
        if st["total"] == 0:
            continue
        industries_arr.append(
            {
                "sector": ind,  # Named 'sector' for table renderer mapping compatibility
                "universe": st["total"],
                "vcp_count": st["vcp"],
                "a20_pct": int((st["a20"] / st["total"]) * 100),
                "a50_pct": int((st["a50"] / st["total"]) * 100),
                "a200_pct": int((st["a200"] / st["total"]) * 100),
                "parent_sector": st["parent"],
            }
        )

    # Load previous history if exists
    prev_history = []
    try:
        with open(out_dir / "sector_breadth.json", encoding="utf-8") as jf:
            prev_data = json.load(jf)
            if "history" in prev_data and isinstance(prev_data["history"], list):
                prev_history = prev_data["history"]
    except Exception:
        pass

    # Today's snapshot entry
    today_str = datetime.now().strftime("%Y-%m-%d")
    new_history_entry = {"date": today_str, "sectors": {}, "industries": {}}

    for sec, st in sector_stats.items():
        if st["total"] == 0:
            continue
        new_history_entry["sectors"][sec] = {
            "universe": st["total"],
            "vcp_count": st["vcp"],
            "a20_pct": int((st["a20"] / st["total"]) * 100),
            "a50_pct": int((st["a50"] / st["total"]) * 100),
            "a200_pct": int((st["a200"] / st["total"]) * 100),
        }

    for ind, st in industry_stats.items():
        if st["total"] == 0:
            continue
        new_history_entry["industries"][ind] = {
            "universe": st["total"],
            "vcp_count": st["vcp"],
            "a20_pct": int((st["a20"] / st["total"]) * 100),
            "a50_pct": int((st["a50"] / st["total"]) * 100),
            "a200_pct": int((st["a200"] / st["total"]) * 100),
            "parent_sector": st["parent"],
        }

    # Filter out today's old record if running multiple times today
    prev_history = [h for h in prev_history if h.get("date") != today_str]
    prev_history.append(new_history_entry)
    prev_history.sort(key=lambda x: x.get("date", ""))
    prev_history = prev_history[-60:]

    breadth_data = {
        "scan_date": today_str,
        "scan_time": scan_time,
        "total_scanned": total,
        "sectors": sectors_arr,
        "industries": industries_arr,
        "history": prev_history,
    }

    try:
        with open(out_dir / "sector_breadth.json", "w", encoding="utf-8") as jf:
            json.dump(breadth_data, jf, indent=2)
        print(f"✅ JSON saved: {out_dir / 'sector_breadth.json'}")
    except Exception as je:
        print(f"❌ Error writing sector_breadth.json: {je}")

    # 2. sector_stocks.json
    def serialize_stock(r):
        return {
            "symbol": r["symbol"],
            "company": r["company"],
            "price": r["current"],
            "mktcap": r["market_cap"],
            "r30": r["r30"],
            "r60": r["r60"],
            "r90": r["r90"],
            "dist52": r["dist52"],
            "drawdown": r["drawdown"],
            "setup": r["setup"],
            "final_score": r["final_score"],
            "vcp_score": r["vcp_score"],
            "grade": r["grade"],
            "rs_rating": r["rs_score"],
        }

    sectors_stocks_map = {}
    for sec in sector_stats:
        sec_stocks = [serialize_stock(r) for r in results if r["sector"] == sec]
        sectors_stocks_map[sec] = {
            "universe": sector_stats[sec]["total"],
            "vcp_count": sector_stats[sec]["vcp"],
            "scan_time": scan_time,
            "stocks": sec_stocks,
        }

    industries_stocks_map = {}
    for ind in industry_stats:
        ind_stocks = [serialize_stock(r) for r in results if r["industry_group"] == ind]
        industries_stocks_map[ind] = {
            "universe": industry_stats[ind]["total"],
            "vcp_count": industry_stats[ind]["vcp"],
            "scan_time": scan_time,
            "stocks": ind_stocks,
        }

    stocks_data = {
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
        "scan_time": scan_time,
        "sectors": sectors_stocks_map,
        "industries": industries_stocks_map,
    }

    try:
        with open(out_dir / "sector_stocks.json", "w", encoding="utf-8") as jf:
            json.dump(stocks_data, jf, indent=2)
        print(f"✅ JSON saved: {out_dir / 'sector_stocks.json'}")
    except Exception as je:
        print(f"❌ Error writing sector_stocks.json: {je}")

    # --- DISABLED FOR GITHUB ACTIONS TO SAVE REPO SPACE ---
    # xlsx_out = out_dir / 'vcp_scanner_results.xlsx'
    # print(f'Generating Excel report...')
    # if export_excel(results, xlsx_out):
    #     print(f'✅ Excel saved: {xlsx_out}')


if __name__ == "__main__":
    main()
