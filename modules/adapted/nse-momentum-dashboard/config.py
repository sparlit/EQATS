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
Central configuration.

Kite Connect credentials (api_key/api_secret/access_token) and the
dashboard login live in cache/state.db (see state_db.py) -- .env is only
used to BOOTSTRAP them once, the first time this app runs with an empty
database. After that first run, updating .env does nothing for these
values; use the dashboard's own settings forms (Cockpit's "Change
dashboard password" / "Kite API settings") instead, since the DB is the
live source of truth from then on.

Create a `.env` file next to this one (only needed for that first run):

    KITE_API_KEY=your_kite_api_key
    KITE_API_SECRET=your_kite_api_secret
    KITE_ACCESS_TOKEN=            # filled daily after login flow
    DASHBOARD_USERNAME=your_username     # optional -- defaults to "Admin"
    DASHBOARD_PASSWORD=your_password     # optional -- defaults to "Admin"

    # Optional push notifications (see notify.py) -- read directly by
    # notify.py, not by this file. Leave VAPID_PRIVATE_KEY blank to disable;
    # nothing else depends on it being set.
    DASHBOARD_URL=               # e.g. https://your-host.ts.net:8501/ --
                                  # included as a clickable link in alerts

    # Browser push (see notify.py's docstring for the keygen one-liner)
    VAPID_PRIVATE_KEY=
    VAPID_PUBLIC_KEY=
    VAPID_CLAIMS_EMAIL=          # any contactable email -- not verified,
                                  # just required by the Web Push spec
    PUSH_SERVER_PORT=8503        # push_server.py's own port
"""

import os

import state_db
from dotenv import load_dotenv

load_dotenv()

state_db.ensure_kite_credentials_seeded(
    os.getenv("KITE_API_KEY", ""),
    os.getenv("KITE_API_SECRET", ""),
    os.getenv("KITE_ACCESS_TOKEN", ""),
)
_kite_creds = state_db.get_kite_credentials()

KITE_API_KEY = _kite_creds["api_key"]
KITE_API_SECRET = _kite_creds["api_secret"]
KITE_ACCESS_TOKEN = _kite_creds["access_token"] or ""

# Dashboard login gate (dashboard.py) -- placeholders on purpose, not a real
# credential store. This app places real orders and shows real fund
# balances, so change these via the Cockpit's "Change dashboard password"
# section before exposing it beyond your own machine -- "Admin"/"Admin" is
# one of the most commonly attacked default credential pairs that exists.
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "Admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "Admin")

# ---------------------------------------------------------------------------
# Universe: NSE F&O-eligible stocks only (~210 names), fetched live from
# https://www.nseindia.com/api/underlying-information and cached weekly.
#
# Why F&O-only: these are NSE's most liquid stocks (the exchange's own
# eligibility rules screen for market cap and quarter-sigma order size), so
# slippage stays low — and slippage is precisely what erodes momentum edges
# in live trading. They can also be hedged with options if a position sours.
#
# Override with a manual list here if you ever want to test a custom set.
# ---------------------------------------------------------------------------
import fno_universe as _fno

UNIVERSE_OVERRIDE: list[str] = []  # non-empty = use this instead


def get_universe(refresh: bool = False) -> list[str]:
    base = (
        UNIVERSE_OVERRIDE
        if UNIVERSE_OVERRIDE
        else _fno.tradable_on_kite(_fno.get_fno_universe(force_refresh=refresh))
    )
    skipped = set(state_db.get_skipped_symbols())
    return [s for s in base if s not in skipped]


def refresh_universe() -> None:
    """Recomputes UNIVERSE and UNIVERSE_RAW in place, applying the current
    skip list (state_db.skipped_symbols, editable from Admin -- "Skip
    stocks from scanner"). Called once below at import time, and again
    after every Admin-page skip/un-skip so the change takes effect
    immediately for every module that reads config.UNIVERSE -- screener.py,
    backtest.py, fundamentals_agent.py, dashboard.py all do `import config`
    and then read `config.UNIVERSE` fresh at call time (never `from config
    import UNIVERSE`), so reassigning the name here is all that's needed;
    same live-update pattern as config.STRATEGY.update() elsewhere in this
    app -- no dashboard/service restart required.

    UNIVERSE_RAW is the full F&O-eligible list, NEVER skip-filtered --
    skipping a stock is a "don't scan/trade this" preference, not a claim
    that NSE's actual F&O list is smaller, so anything just reporting the
    exchange's real count (e.g. the sidebar's "F&O universe: N stocks")
    should read UNIVERSE_RAW, not UNIVERSE."""
    global UNIVERSE, UNIVERSE_RAW
    UNIVERSE_RAW = _fno.get_fno_universe(verbose=False)
    skipped = set(state_db.get_skipped_symbols())
    UNIVERSE = [s for s in UNIVERSE_RAW if s not in skipped]


# Lazily-resolved default universe (safe at import time — falls back to the
# bundled snapshot if NSE/Kite are unreachable). UNIVERSE excludes anything
# in the manual skip list; UNIVERSE_RAW never does -- see refresh_universe().
UNIVERSE: list[str] = []
UNIVERSE_RAW: list[str] = []
refresh_universe()

BENCHMARK = "NSE:NIFTY 50"  # for relative strength

# ---------------------------------------------------------------------------
# Strategy parameters (see README for the research behind each).
#
# _STRATEGY_DEFAULTS below is only the SEED/fallback -- state_db.strategy_config
# is the live source of truth from first run onward (same pattern as Kite
# credentials above), editable from the dashboard's Admin page without a code
# change or restart. Change the research defaults themselves here; change your
# own live values from the Admin page.
# ---------------------------------------------------------------------------
_STRATEGY_DEFAULTS = {
    # Momentum lookbacks (Jegadeesh & Titman 1993: 3-12m formation works for
    # 3-6m holding; we skip the most recent week to dodge short-term reversal)
    "mom_lookback_days_short": 63,  # ~3 months
    "mom_lookback_days_long": 126,  # ~6 months
    "skip_recent_days": 5,
    # 52-week high proximity (George & Hwang 2004)
    "near_high_threshold": 0.85,  # price >= 85% of 52w high to qualify
    # Trend structure
    "ema_fast": 50,
    "ema_slow": 200,
    # RSI regime: momentum names trade 40-80; avoid parabolic >80 entries.
    # rsi_max raised 78 -> 80 after an A/B backtest (5y, max_positions=4):
    # CAGR 7.36->8.15%, Sharpe 1.14->1.25, max DD -6.62->-6.51%, profit
    # factor 1.9->2.06 -- a clean, consistent improvement (flat-or-better in
    # 5 of 6 calendar years), not one lucky year. A separate idea tested
    # alongside this one -- relaxing rsi_max specifically for ALREADY-HELD
    # positions (so overbought alone wouldn't trigger a sell) -- made every
    # metric worse and was discarded entirely, same as the regime filter and
    # beta scoring before it: this simple threshold-only change is the one
    # that earned a spot.
    "rsi_period": 14,
    "rsi_min": 45,
    "rsi_max": 80,
    # Backtest-only (for now): decouples the RSI ceiling used to decide
    # whether an ALREADY-HELD position should be sold from the entry-band
    # check above. See the rsi_max comment just above -- this exact idea
    # (widen the ceiling for held positions only, so overbought alone
    # wouldn't trigger a sell) was already A/B tested once and made every
    # metric worse, hence off by default. Re-exposed here, wired into the
    # Backtest UI, for re-testing against today's data/universe rather
    # than trusting that one past result forever.
    "rsi_exit_gate_enabled": False,
    "rsi_exit_max": 80,
    # Backtest-only (for now): extra higher-timeframe confirmation gate --
    # weekly AND monthly price must each be above their own 200-period
    # EMA (falls back to a 50-period EMA when there isn't enough
    # resampled history for 200 yet). Originally also required weekly/
    # monthly RSI above a floor, dropped after real-run data showed that
    # (4 stacked conditions total) caused excessive rebalance-exit churn
    # -- a held position only needed one condition to wobble near its
    # threshold to get force-sold. Off by default, untested -- add to
    # the Backtest UI first and A/B before considering for live.
    "weekly_monthly_gate_enabled": False,
    # BACKTEST-ONLY experiment, off by default: replaces trend_ok's usual
    # 3-condition definition (above_ema50 & above_ema200 & ema50_rising)
    # with a plain 9/21 EMA cross -- trend_ok = ema9 above ema21 (ema_fast,
    # 21 in this config), trend_ok = False once ema9 crosses below it.
    # Requested 2026-09-12 to re-test after OFSS/COFORGE both failed the
    # existing trend gate on a short-term pullback despite still being
    # well above their 55-EMA -- see indicators.compute_snapshot's
    # ema9_above_ema21 field.
    "trend_gate_ema9_21_cross_enabled": False,
    # Risk management
    "atr_period": 14,
    "atr_stop_multiple": 2.5,  # initial stop = entry - 2.5*ATR
    "risk_per_trade_pct": 0.5,  # % of capital risked per position
    "max_positions": 10,
    # Trailing stop (chandelier-style): ratchets the stop up to
    # highest_close_since_entry - trailing_atr_multiple*ATR as a position
    # gains, never back down. A real 5-year sweep found this forms an
    # inverted-U across multiples (too narrow whipsaws, too wide barely
    # trails at all), peaking at 4.0 (CAGR 24.30% vs baseline 22.51%,
    # Sharpe 1.73 vs 1.50, max DD -14.37% vs -18.06%) -- see the README's
    # "Trailing stop" section for the full sweep, including that adding
    # either the fundamental gate or the sector bonus on top of it gave
    # back the improvement rather than adding to it. This is the one
    # experimental feature from that round that earned a spot in the
    # default strategy -- sector_bonus_weight and the (also-tried,
    # removed) regime filter did not.
    "trailing_stop_enabled": True,
    "trailing_atr_multiple": 4.0,
    # Push a ratcheted trailing stop straight to the real broker GTT the
    # moment it's computed (live_rebalance.py's compute_stop_updates),
    # rather than waiting for a manual "Apply stop updates" click --
    # same automation level as the gap-down safety check. Deliberately
    # not something that needed a backtest: this only changes WHO/WHEN
    # pushes an already-decided stop value to the broker, not the stop
    # formula or any trading decision itself, and it only ever tightens
    # risk (ratchets up), never loosens it or places a new order.
    "auto_apply_stop_updates": True,
    # Fundamental gate: xbrl_parser's sector-aware value_score/bank_score/
    # nbfc_score/etc total (0-100), computed from primary-source XBRL via
    # fundamentals_agent.fno_value_scan(). 50 is a rough "average-or-better
    # across profitability, health, and growth" bar — tune to taste.
    "min_fundamental_score": 50.0,
    # Turned on after a 5-year A/B backtest (equal-weight capital sizing --
    # matches live_rebalance.py's actual sizing -- max_positions=10): a real
    # trade-off, not a clean win -- CAGR 44.66%->42.72%, Sharpe 1.62->1.60,
    # profit factor 2.15->2.07, but max drawdown improves -28.65%->-24.47%.
    # Wins 3 of 6 calendar years (2021/2022/2025, the calmer ones), loses in
    # the two blowout years 2023/2024 and 2026 YTD. Kept on for the
    # drawdown reduction -- re-run the A/B yourself before flipping back.
    # The fundamental score is always shown (Screener, Live Rebalance)
    # whenever fundamentals data is available, regardless of this flag --
    # see screener.apply_gates()'s docstring.
    "fundamental_gate_enabled": True,
    # Fundamental-score ranking tilt (screener.score(), on top of the gate
    # above -- this affects WHERE a gate-passing candidate ranks, the gate
    # only ever excludes/includes). A 5-year A/B sweep (equal-weight
    # sizing, max_positions=10) found an inverted-U peaking near 0.5:
    # weight 0->0.5->1.0->2.0 gives CAGR 43.70%->43.03%->38.88%->27.93%,
    # Sharpe 1.62->1.64->1.56->1.26, but max drawdown improves at 0.5
    # specifically (-24.61%->-20.30%) before getting worse again at 1.0
    # (-26.72%). 0.5 is a near-wash on CAGR/win-rate (51.7%->50.6%) for a
    # real ~4pp drawdown improvement -- kept for the same reasoning as the
    # gate itself. Anything above 0.5 is a clear net negative.
    "fundamental_bonus_weight": 0.5,
    # Sector relative-strength bonus (see sector_universe.py): tilts ranking
    # toward stocks in currently-outperforming sectors. 0 = off, matching
    # this codebase's pattern of shipping a new scoring dimension disabled
    # until an A/B backtest earns it (see the removed breakout-bonus tier).
    "sector_bonus_weight": 0.0,
    "sector_rs_lookback_days": 126,  # matches mom_lookback_days_long
    # Sector diversification (backtest-only for now, off by default): the
    # sector bonus above is a pure ranking TILT -- it can still leave a
    # portfolio stacked into one hot sector if that sector's stocks simply
    # score highest (real example: 8 of 10 top candidates were all Pharma
    # on one real scan). This is a hard constraint instead -- restricts
    # entries to stocks whose best-matching sector is currently among the
    # top_n_sectors strongest, AND caps how many open positions any single
    # sector can hold at once (max_positions_per_sector), enforced at buy
    # time in run_backtest()'s allocation step. Untested -- verify from
    # the Backtest UI before considering for live.
    "sector_diversification_enabled": False,
    "top_n_sectors": 3,
    "max_positions_per_sector": 3,
    # Alternative to ranking sectors on raw relative-strength alone --
    # blends RS with the sector index's own 52-week-high proximity and
    # breadth (% of the sector's own stocks passing the technical gates)
    # into one composite score. Backed by real literature, see
    # sector_universe.sector_composite_score()'s docstring: Moskowitz &
    # Grinblatt (1999) for industry momentum, George & Hwang (2004) for
    # 52-week-high proximity as an independent predictive signal, IBD/
    # O'Neil "Group Relative Strength" for breadth. Off by default --
    # only has any effect when sector_diversification_enabled is also on
    # (it changes which sectors count as "top N"). Untested -- verify
    # from the Backtest UI, A/B against the plain-RS version, before
    # considering for live.
    "sector_composite_score_enabled": False,
    # Overhead-resistance tilt (see resistance_zones.py): tilts ranking
    # toward stocks with more "clean room" before the nearest multi-year
    # price zone above them (a level swing-touched repeatedly in the past
    # -- latent overhead supply that can cap a rally and trigger the
    # stop, even when every other momentum/trend signal looks fine at
    # entry). 0 = off, same pattern as sector_bonus_weight -- ships
    # disabled until an A/B backtest earns it a spot. Backtest-only for
    # now (needs deep history via load_long_history_cached, same as the
    # weekly/monthly gate).
    "resistance_zone_weight": 0.0,
    "resistance_zone_lookback_years": 5.0,  # receding window, not a fixed anchor
    "resistance_zone_pivot_window": 10,  # trading days each side to confirm a swing pivot
    "resistance_zone_cluster_tolerance_pct": 0.03,  # nearby pivots within this % cluster into one zone
    "resistance_zone_search_pct": 0.20,  # ignore zones more than this far above price
    # Market regime filter (backtest-only for now): caps how many NEW
    # positions may be open at once when NIFTY 50 itself is below its own
    # long-term trend -- a classic trend-following risk control (only
    # trade long aggressively when the market you're trading IN is
    # itself trending up). Never force-sells an existing position purely
    # because the regime flipped, same "blocks new entries only"
    # philosophy as the sector diversification cap. 0 = off by default,
    # untested -- verify from the Backtest UI before considering for live.
    "regime_filter_enabled": False,
    "regime_ema_period": 200,
    "regime_position_multiplier": 0.5,
    # Entry confirmation (backtest-only for now): requires a stock to have
    # stayed in the confirm-pool (top entry_confirm_pool_size candidates by
    # score, default max_positions*2 -- same convention as keep_zone) for
    # this many CONSECUTIVE rebalance events before a NEW buy is allowed.
    # Filters out one-day/one-rebalance "wonder" ranks that reverse right
    # after qualifying. Never affects sells -- only gates new entries, same
    # "blocks new entries only" philosophy as the regime filter above.
    # TESTED AND DISCARDED as a default, same as beta scoring and the first
    # regime-filter attempt: a 5.6yr PDF-config backtest (2021-2026, regime
    # filter above already ON) found 0 -> 2 made every headline metric
    # WORSE at once -- CAGR 38.65%->37.26%, Sharpe 1.64->1.60, max drawdown
    # -30.67%->-33.10% -- despite a small win-rate lift (35.6%->37.6%).
    # Kept here, off by default, as a re-testable toggle from the Backtest
    # UI rather than deleted outright, in case a different config responds
    # differently -- but do not expect it to help.
    "entry_confirm_days": 0,
    "entry_confirm_pool_size": None,
    # MAD Volatility Trail stop (backtest-only for now): replaces BOTH the
    # initial ATR stop and the ongoing ATR trailing stop with the trail's
    # own one-sided ratcheting lower band (see mad_trail_strategy.py) --
    # mutually exclusive with atr_stop_multiple/trailing_atr_multiple/
    # trailing_stop_enabled above, which stay untouched and take over
    # automatically whenever the trail isn't a sensible support for a
    # given entry (not in a bull MAD-regime, or the band sits above
    # price). A 5.6yr PDF-config backtest (2021-2026, regime filter ON,
    # entry-confirm OFF) found this combination -- med_len=21, mad_len=21,
    # dev_factor=2, atr_floor_mult=2 -- raised CAGR from 33.82% to 36.98%
    # AND shrank max drawdown (-27.59% -> -25.84%) at the same time, broad
    # -based across 5 of 6 calendar years, not one lucky year. False by
    # default -- verify against your own config from the Backtest UI
    # before considering for live.
    "mad_stop_enabled": False,
    "mad_stop_med_len": 21,
    "mad_stop_mad_len": 21,
    "mad_stop_dev_factor": 2.0,
    "mad_stop_atr_floor_mult": 2.0,
    "history_days": 1200,  # calendar days of candles to fetch
    # Equal-weight capital allocation (screener.capital_position_size) vs.
    # the risk-based sizing above (screener.position_size, what backtest.py
    # uses when this is off). False reproduces the original behavior exactly
    # -- opt-in until an A/B backtest earns it a spot as the default, same
    # pattern as sector_bonus_weight/trailing_stop_enabled. live_rebalance.py
    # always uses capital_position_size regardless of this flag (a live/UX
    # decision made independently -- see its own module for why); this flag
    # only controls backtest.py's simulation, for comparing the two.
    "capital_equal_weight_sizing": False,
    # screener.allocate_equal_weight_buys(): a from-scratch replacement for
    # capital_position_size()'s one-symbol-at-a-time sizing, which greedily
    # skipped an unaffordable top-ranked candidate for whatever cheaper,
    # lower-ranked stock it found next (this is what let a rank #9 stock
    # get bought over rank #1-8 ones when cash was thin -- the real
    # incident that prompted this feature). Decides the WHOLE day's/run's
    # allocation in one pass instead: cross-slot borrowing within
    # equal_weight_tolerance_pct, a partial (not skipped) fill when even
    # borrowing can't reach full target, a hard stop (no substitution) only
    # once nothing at all is affordable, and topping up existing
    # under-target holdings with any leftover cash. A 5-year A/B (equal-
    # weight sizing, max_positions=10, on top of the fundamental gate +
    # bonus weight above) found tolerance=0.20 beats the old per-symbol
    # fill on every metric at once: CAGR 43.06%->44.39%, Sharpe 1.64->1.67,
    # max drawdown -20.30%->-19.58%, profit factor 2.10->2.12 -- verified
    # via instrumented run that the top-up path (103/1236 days) and
    # partial-fill path (127/1236 days) both genuinely fire, not just
    # theoretically reachable. live_rebalance.py uses this whenever it's
    # on; False reverts to capital_position_size's original one-at-a-time
    # behavior for rollback.
    "advanced_equal_weight_sizing": True,
    "equal_weight_tolerance_pct": 0.20,
    # Fully automate placing the proposed sells/buys/top-ups as real
    # orders, immediately after the SCHEDULED daily rebalance job computes
    # them (live_rebalance.py's main() only -- deliberately NOT the
    # dashboard's manual "Run today's scan" button, so clicking that to
    # look at today's candidates never itself fires real orders; same
    # split as check_gap_down_stops() being scheduled-only automation).
    # False by default -- unlike auto_apply_stop_updates (which only ever
    # tightens an existing stop, low-risk), this places brand-new orders
    # and exits real positions, so it stays an explicit opt-in only once
    # you're confident in the proposal quality. When on, uses the exact
    # same execute_sells()/execute_buys()/execute_top_ups() functions the
    # dashboard's manual buttons call, so the two paths can't drift apart.
    "auto_execute_trades": False,
    # DP (Depository Participant) charge CDSL/your broker debits per scrip
    # per day you sell -- state_db.close_trade() auto-logs this as a
    # cash_flows entry every real exit (any path: rebalance sell, gap-down
    # stop, manual square-off, GTT-fill reconciliation), so it's never
    # missed the way a manually-remembered ledger entry can be. 0 disables
    # this entirely (no cash_flows entry posted).
    "dp_charge_per_scrip": 15.34,
    # Idle-cash sweep: park uninvested cash in a liquid-fund ETF
    # (cash_sweep_symbol) so it earns some interest instead of sitting
    # idle, redeeming just enough automatically whenever a real buy/top-up
    # needs more cash than what's free. False by default -- like
    # auto_execute_trades, this places real automatic orders (on a NEW
    # instrument the app has never traded before), so it's a deliberate
    # opt-in, not silently on. Buying it carries no DP charge (only a SELL
    # does, per real CDSL rules), so there's no minimum sweep-in amount --
    # every idle rupee gets swept once this is on. See live_rebalance.
    # sweep_idle_cash()/ensure_cash_for_buys()/get_cash_sweep_holding().
    "cash_sweep_enabled": False,
    "cash_sweep_symbol": "LIQUIDCASE",
    # Rebalance cadence: "daily" re-evaluates the sell/keep-zone rule every
    # time the scheduled scan runs (Mon-Fri); "monthly" only evaluates it
    # on the first trading day of each calendar month (nse_holidays.
    # is_month_start_trading_day), same definition backtest.py's monthly
    # rb_dates uses. New buys/top-ups always fill whatever slots are
    # already open regardless of this setting -- only the SELL decision
    # (rank/200-EMA check) is gated, matching how backtest.py's own daily
    # loop works (watchlist refreshed monthly, but a freed slot gets
    # filled the same day it opens, not held until next rebalance).
    # "daily" is the current default: real 2016-2026 data + a 5-seed
    # synthetic multi-regime test both found it meaningfully reduces max
    # drawdown (roughly -50% -> -35% over 10 years) at a real but smaller
    # cost to CAGR -- a priced trade-off, not a free win, so this is worth
    # re-checking against your own risk tolerance rather than assuming
    # it's forever the right choice.
    "rebalance_cadence": "daily",
    # Intraday "DaysLowVolumnBreakout" strategy (separate from everything
    # above, which is all the CNC swing/momentum strategy) -- the SOLE
    # source of truth intraday_engine.py's __main__ reads at every plain
    # (no-flags) launch to decide paper vs live, so a scheduled daily
    # launch auto-trades live the very next run after this is saved on --
    # no per-day manual step (dashboard.py's page_intraday_dashboard()
    # reads it the same way to label the mode badge). False by default --
    # a currently-running paper engine process does NOT hot-swap, it
    # needs restarting to pick up a change here.
    "intraday_live_enabled": False,
    # Starting capital for the intraday strategy's OWN capital tracks
    # (intraday_capital_state, one row per mode -- kept fully separate
    # from the CNC swing book's cash, and paper/live kept separate from
    # each other so switching to live never inherits paper's simulated
    # P&L). intraday_engine.py's run_live() reads whichever of these two
    # matches the mode it's about to run, instead of a single hardcoded
    # constant, so both are Admin-editable the same way. Each only takes
    # effect the FIRST time that mode actually runs (intraday_db.ensure_
    # capital_seeded() no-ops if that mode's row already exists) --
    # editing either value after that mode has started trading does NOT
    # reset its compounded current_capital, by design.
    "intraday_live_capital": 1_000_000.0,
    "intraday_paper_capital": 1_000_000.0,
}

# Keys the Backtest page's run_cfg-builder overrides from its own widgets
# (dashboard.py's run_cfg block) -- also the exact set "Apply to live" is
# allowed to push from a completed backtest run, so the two can never
# silently drift apart. Everything else in _STRATEGY_DEFAULTS is either an
# Admin-only automation toggle (ADMIN_ONLY_KEYS) or a fixed research
# constant with no UI anywhere (rsi_period, atr_period, regime_ema_period,
# sector_rs_lookback_days, the resistance_zone_* internal knobs) -- neither
# category may ever be overwritten by a stale backtest snapshot.
BACKTEST_TUNABLE_KEYS = (
    "max_positions",
    "rsi_min",
    "rsi_max",
    "trailing_stop_enabled",
    "trailing_atr_multiple",
    "advanced_equal_weight_sizing",
    "capital_equal_weight_sizing",
    "equal_weight_tolerance_pct",
    "fundamental_gate_enabled",
    "fundamental_bonus_weight",
    "min_fundamental_score",
    "mom_lookback_days_short",
    "mom_lookback_days_long",
    "skip_recent_days",
    "rsi_exit_gate_enabled",
    "rsi_exit_max",
    "weekly_monthly_gate_enabled",
    "trend_gate_ema9_21_cross_enabled",
    "near_high_threshold",
    "ema_fast",
    "ema_slow",
    "atr_stop_multiple",
    "mad_stop_enabled",
    "mad_stop_med_len",
    "mad_stop_mad_len",
    "mad_stop_dev_factor",
    "mad_stop_atr_floor_mult",
    "risk_per_trade_pct",
    "sector_bonus_weight",
    "sector_diversification_enabled",
    "top_n_sectors",
    "max_positions_per_sector",
    "sector_composite_score_enabled",
    "resistance_zone_weight",
    "regime_filter_enabled",
    "regime_position_multiplier",
    "entry_confirm_days",
    "entry_confirm_pool_size",
    "history_days",
    "rebalance_cadence",
)
# Admin-only automation toggles, on top of BACKTEST_TUNABLE_KEYS, that make
# up everything the Admin form should render/edit.
ADMIN_ONLY_KEYS = ("auto_apply_stop_updates", "auto_execute_trades")
ADMIN_EDITABLE_KEYS = BACKTEST_TUNABLE_KEYS + ADMIN_ONLY_KEYS

STRATEGY = state_db.get_strategy_config(_STRATEGY_DEFAULTS)
