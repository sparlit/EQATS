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


import datetime
import os

from dotenv import load_dotenv

load_dotenv()

# Credentials — values come from .env, never from this file.
FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID")
FYERS_SECRET_ID = os.getenv("FYERS_SECRET_ID")
FYERS_REDIRECT_URI = os.getenv(
    "FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html"
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Core trading config
# Armed on boot by design: a manual /auto each morning meant missed sessions.
# TRADING_ENABLED still gates everything, and only from 09:30 IST.
AUTO_MODE = True
MAX_SESSION_LOSS_INR = 500  # Cumulative intraday loss that halts the bot
DAILY_TARGET_INR = -1  # -1 = dynamic 5%; a positive value overrides it.
# Once hit, only EXTREME/MAX_CONVICTION signals pass.
INTRADAY_LEVERAGE = 5.0  # Fixed 5× leverage (NSE standard requirement)

# Toggle at runtime with Telegram /mode buy | /mode sell.
TRADE_DIRECTION = "SHORT"  # 'SHORT' or 'LONG'

# A 46-trade replay put 45 ahead of no cap in every phase. 0 disables the exit.
MAX_HOLD_TIME_MINUTES = 45

# Scanner universe filters
SCANNER_GAIN_MIN_PCT: float = 7.5  # Kept in sync with the G1 gate floor
# Held at 18.0 deliberately. NSE upper circuits are commonly 20%, and a short that
# goes limit-up cannot be covered at all — the position carries overnight with a
# margin penalty. 18 keeps entries clear of that.
#
# This is NOT redundant with C0's circuit check, which was the argument for raising
# it to 25.0 on 2026-09-04 (reverted the same day). C0 only runs when the analyzer
# managed to read upper_ckt from the depth feed; that fetch is wrapped in a bare
# `except: pass`, so on any failure upper_circuit stays 0.0 and C0's guard is
# skipped entirely. This ceiling is the backstop for exactly that case.
#
# It is also not a proxy for "20% band": measured bands across this universe run
# from 11% to 41%, so where the band is tighter than 18% the circuit binds first
# and this never applies.
SCANNER_GAIN_MAX_PCT: float = 18.0
# Lowered twice from 333,333: low-float movers cleared the old floor ~26 min
# after the move. Admits thinner books, so watch slippage.
SCANNER_MIN_VOLUME: int = 111111
SCANNER_MIN_LTP: float = 40.0  # Filter sub-₹40 manipulation vehicles

# Fyers grants either 4-5x or exactly 1.0x (= MIS refused), nothing between, so
# 3.5 sits in an empty gap and is not a number to tune. An unknown reading never
# blocks: the scanner fails open and the broker rejection is the backstop.
SCANNER_MIN_LEVERAGE: float = 3.5

# Per-scan budget for the leverage screen. Past it, symbols pass unscreened
# rather than delay the scan, which main.py times out at 90s.
SCANNER_LEVERAGE_BUDGET_SECONDS: float = 15.0
# Lowered from 0.382 on 2026-09-04. 0.382 was picked for being a Fibonacci number,
# not from measurement, and it sat directly on top of the population: 98 of 155
# quality rejections over 2-4 Sep were at ratios of 0.34 or better. NSE:ANTELOPUS-EQ
# was dropped at 0.38 against 0.382 and stayed dropped for the rest of the day while
# it ran to +17%. Violent movers are wick-heavy by nature, so the old floor selected
# against exactly the setups this strategy exists to catch.
CANDLE_BODY_RATIO_MIN: float = 0.34

DAY_GAIN_PCT_THRESHOLD = 7.5  # Alias for SCANNER_GAIN_MIN_PCT, still read by legacy paths

SCANNER_PARALLEL_WORKERS = 3  # Above 3, Fyers starts returning 429s
WS_TICK_FRESHNESS_TTL_SECONDS = 180.0

# Strategy: BackToVWAPShort
# C1 gate: minimum stretch, in SD. Lowered from 3.3 on 2026-09-04 at the operator's
# instruction. C1 rejects 61-70% of all evaluations, and the rejected symbols pile up
# immediately under the old floor — 20 of 55 over 2-4 Sep peaked between 3.20 and
# 3.30, and not one cleared. That clustering is the signature of a floor set slightly
# too tight rather than of setups that genuinely failed.
#
# Against that: June's +38.9% was earned at 3.3, and this has never been measured
# head-to-head. Revert to 3.3 first if results degrade.
STRATEGY_VWAP_SD_FLOOR: float = 3.2
STRATEGY_VWAP_SD_HIGH: float = 5.0  # HIGH confidence tier threshold
STRATEGY_VWAP_SD_EXTREME: float = 6.0  # EXTREME confidence tier threshold
STRATEGY_REQUIRE_FAILED_AUCTION: bool = True  # Hard gate: require auction failure behavior
STRATEGY_VOL_FADE_MAX_RATIO: float = 0.65  # Below this counts as fading; never relaxed
# Restored to June's values on 2026-08-30. July shortened both; June's +38.9%
# was earned at 15 and 25, and the two have never been measured against
# each other.
STRATEGY_VOL_FADE_LOOKBACK: int = 15  # Candles to look back for volume baseline
STRATEGY_RSI_DIVERGENCE_WINDOW: int = 25  # Window for swing-based RSI divergence check
STRATEGY_MOMENTUM_DECAY_RATIO: float = 0.85  # Fast slope must be < slow * this ratio

# Exit engine and risk multipliers
SL_ATR_MULTIPLIER = 0.5
SL_MIN_TICK_BUFFER = 3

P52_CLEANUP_ON_STOP_FOCUS: bool = True

#   'SCALE'  — 50% at the midpoint, rest runs to the VWAP target (pre-30-Jun)
#   'SINGLE' — 100% at the midpoint
#   'OFF'    — stop-loss and EOD only
# A 46-trade replay ranked SCALE > SINGLE > OFF, but the intervals span zero.
# The TP only ever changes winners: losers hit the stop first under all three.
TP_MODE: str = "SCALE"

# Moves the stop to breakeven once the SCALE partial fills. On its own switch
# because it is the one exception to the standing "no breakeven SL" rule.
P52_BREAKEVEN_AFTER_TP1: bool = True

# Master switch for the original strategy (C1-C6 exhaustion reversal at a VWAP
# stretch). Turned OFF 2026-09-21 at the operator's instruction so that one week
# isolates TopCoilShort with no other detector firing. With this False the bot
# takes ONLY top-coil signals; the C0 pre-filters that live inside
# back_to_vwap.evaluate stop running with it, which is why TopCoilShort carries
# its own copies (TC0) rather than relying on them.
BACKTOVWAP_ENABLED: bool = False

# --- TopCoilShort: the coil-at-the-high breakdown ------------------------------
# A SECOND detector, running beside BackToVWAPShort, not replacing it. It fires on
# contraction at the day's high; C1 fires on expansion away from VWAP. A range
# tighter than 1% within 1.5% of the high clears the 3.2 SD floor 0.31% of the
# time, so the existing stack is blind to this pattern by construction.
#
# MEASURED, AND IT DOES NOT MAKE MONEY. 997 stock-days (Jun-Sep 2026), 0.212%
# entry slippage plus 0.106% statutory cost, stop above the coil high, held to the
# 15:10 square-off, simulating the engine's own validation gate:
#
#   gain floor   n     mean/trade   t       bootstrap 95% CI
#   10.0       262     -0.223%    -1.42     [-0.518, +0.092]
#   11.0       211     -0.070%    -0.37     [-0.423, +0.305]
#   12.0       181     -0.124%    -0.60     [-0.517, +0.294]   <- shipped
#   13.0       144     -0.004%    -0.02     [-0.434, +0.460]
#   14.0       112     -0.124%    -0.52     [-0.573, +0.357]
#
# Every cell is negative and every interval contains zero. An earlier pass showed
# +0.091% at an 11% floor; that was an artifact of filling at the break LEVEL
# while entering on a bar CLOSE. Honest fills removed it entirely. See
# md/FINDINGS_2026-09-21_top_coil.md.
#
# Driving the SHIPPED detector bar by bar over the same 993 stock-days, through a
# simulation of this engine's own validation gate, scores -0.165%/trade at the
# 12.0 floor over 175 trades (CI [-0.560, +0.255], 3.6 trades/session, median risk
# 1.69%). That end-to-end figure is the one to trust: it is the code below, not a
# harness. Re-run it before changing any threshold here —
# md/replay/11_verify_live_detector.py.
#
# CORRECTION, 2026-09-28. Every figure above charged 0.212% entry slippage, read
# from the bot's own "[ENTRY] ... slippage" lines. That line compared the fill with
# the SIGNAL price, so 0.094pp of it was the move from signal to trigger, and it
# printed only fills worse than 0.1%. Against the trigger, over 32 fills, slippage
# was 0.118% (itself biased high by the unlogged good fills). Re-run on 194 trades
# (Jun-24 Sep) with 0.118% entry, 0.08% on stop fills and the gate's real 15-minute
# expiry: -0.007%/trade, CI [-0.385, +0.389]. Flat, not losing, and still no edge:
# held to 15:10 with no stop at all, the short is right 51% of the time.
#
# The stop stays where it is. Of the trades it closes, 70% kept rising (median
# +0.95% above entry at 15:10). Wider stops were tested and none is significant —
# entry +3%: +0.046%, entry +5%: +0.158%, no stop: +0.296% (t=1.30) — while the
# worst single trade grows from -2.7% to -7.4%. ASTEC and KSCL (22 and 24 Sep),
# stopped and then collapsing, are the 30%. md/replay/12_stop_geometry.py.
#
# The floor is 12.0 on BASE-RATE grounds, not because the sweep prefers it — the
# sweep cannot tell these cells apart, and 13.0 is its best corner, which is
# exactly the kind of choice that keeps being wrong here. Independent of any
# backtest, a coil at the high has an up/down excursion ratio of 1.25 below ~12%
# (a bull flag — this would be shorting INTO the drift) and 0.82 above it, with
# 0.56/0.60/0.59 above 15% across three separate months. 12.0 is where the base
# rate starts supporting the trade at all. Do not lower it to widen the funnel.
TOPCOIL_ENABLED: bool = True
TOPCOIL_GAIN_MIN_PCT: float = 12.0
TOPCOIL_GAIN_MAX_PCT: float = 30.0  # above SCANNER_GAIN_MAX_PCT on purpose: the
# pattern is strongest on the biggest movers
TOPCOIL_COIL_BARS: int = 15  # 1-minute bars forming the range
TOPCOIL_NEAR_HOD_PCT: float = 1.5  # range high must sit within this of the HOD
TOPCOIL_MAX_RANGE_PCT: float = 2.0  # and the range must be at least this tight
TOPCOIL_BREAK_BUFFER_PCT: float = 0.1  # trigger sits this far below the coil low
TOPCOIL_FIRST_MIN: int = 585  # 09:45 — no coil is meaningful before this
TOPCOIL_LAST_MIN: int = 880  # 14:40 — past this there is no room to work

# RSI take-profit on top-coil shorts (operator's rule, 30 Sep 2026): once the trade
# is in profit, cover when the 1-minute RSI(14) closes below 40, because a relief
# rally follows. The rally is real — after the first such dip, price bounced within
# 30 minutes in 82% of 147 historical cases (median +1.02%).
#
# What it does to the money, over 190 trades with identical entries:
#                     net/trade  win rate  stopped out  per-trade swing  max drawdown
#   hold to 15:10      +0.058%     36%        53%           2.76%          -39.3%
#   RSI<40 cover       +0.009%     66%        20%           1.14%          -16.8%
# The difference in average (-0.049pp, t=-0.27) is noise; the difference in risk
# is not. It trades the rare big afternoon slide (best trade +9.96% -> +3.28%) for a
# far steadier ride, since after the bounce price is usually lower again by 15:10.
# Thresholds of 38, 35 and 30 all measured worse than 40. The first 5 minutes are
# ignored because the breakdown that triggers the entry drags RSI under 40 by
# itself (NSE:FERMENTA-EQ read 39.6 on its entry bar on 29 Sep).
TOPCOIL_RSI_TP_ENABLED: bool = True
TOPCOIL_RSI_TP_THRESHOLD: float = 40.0
TOPCOIL_RSI_TP_PERIOD: int = 14
TOPCOIL_RSI_TP_SKIP_MINUTES: int = 5  # completed bars after the entry bar
TOPCOIL_RSI_TP_MIN_CANDLES: int = 30  # warm-up; fewer and the rule stays off

LOG_FILE = "logs/bot.log"

RVOL_VALIDITY_GATE_ENABLED = True
RVOL_MIN_CANDLES = 15

ETF_CLUSTER_DEDUP_ENABLED = True
ETF_CLUSTER_KEYWORDS = ["SILVER"]

# MarketSession flips this on at 09:30 IST; nothing trades while it is False.
TRADING_ENABLED = False

MARKET_SESSION_CONFIG = {"allow_postmarket_sleep": True, "telegram_state_transitions": True}


def set_trading_enabled(val: bool):
    global TRADING_ENABLED
    TRADING_ENABLED = val


def minutes_since_market_open() -> float:
    """Calculate minutes elapsed since 09:15 IST today."""
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.datetime.now(tz)
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now < market_open:
        return 0.0
    delta = now - market_open
    return delta.total_seconds() / 60.0


P81_TELEGRAM_MENU_ENABLED = True
P81_TELEGRAM_RATE_LIMIT_HZ = 2

# Local candle engine
P82_LOCAL_CANDLES_ENABLED = True
P82_MAX_LOCAL_CANDLES = 500

# enrich_dataframe computes a cumulative VWAP over whatever frame it is given,
# so the frame length IS the anchor. ROLLING measures a fresh extension over the
# last VWAP_ROLLING_BARS; SESSION measures distance from the day's average and
# stays elevated all day on a trender. SESSION is textbook-correct and fixes a
# real sign defect, but ROLLING is what the profitable run was measured on.
# A deliberate bet at n=4 vs 11, not a demonstrated fact.
VWAP_ANCHOR_MODE: str = "ROLLING"
VWAP_ROLLING_BARS: int = 100

MARKET_REGIME_CONFIG = {"strong_trend_threshold": 0.015}
ENABLE_MARKET_REGIME_FILTER = False  # Nifty 50 trend block, currently off

# Stretch above which G9 (higher-timeframe confluence) is bypassed. Lowered from 5.0
# on 2026-09-04. G9 blocks on "Momentum Accel" and "Sustained Trend", but a parabolic
# pump IS accelerating momentum on a 15-minute chart, so G9 was structurally vetoing
# the setups this strategy hunts. On 4 Sep NSE:JINDWORLD-EQ passed all six conditions
# at +17.6% gain with a VAH_REJECTION pattern and SD=4.09, and G9 killed it. Of the
# three G9 blocks over 2-4 Sep, this recovers two (SD 4.09 and 4.18); MOREPENLAB at
# 3.95 stays blocked. Only signals that already cleared every other gate are affected.
P61_G9_BYPASS_SD_THRESHOLD = 4.0
P61_G9_ACCEL_REJECT_THRESHOLD = 0.5
P61_G9_STALL_PASS_THRESHOLD = 0.1

P58_G12_USE_CANDLE_CLOSE = False
P65_AMT_ENABLED = True
