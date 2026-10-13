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
analyzer.py — Thin orchestrator for the ShortCircuit strategy.

Responsibilities:
1. Data fetching (REST / local candle cache)
2. Enrichment (VWAP, ATR, slopes)
3. Pre-filters (candle count, circuit guard, gain floor, momentum blocker)
4. Delegation to BackToVWAPShort strategy for signal evaluation
5. Signal finalization (SL calc, signal dict, CSV/ML logging)

All feature computation lives in features.py.
All strategy logic lives in strategy/back_to_vwap.py.
"""

import concurrent.futures
import csv
import datetime
import logging
import os
from datetime import time as dtime
from typing import Any

import pandas as pd
from shortcircuit import config
from shortcircuit.broker.rest_limiter import rest_limiter
from shortcircuit.execution.signal_manager import get_signal_manager
from shortcircuit.observability.gate_result_logger import GateResult, get_gate_result_logger
from shortcircuit.observability.ml_logger import get_ml_logger
from shortcircuit.strategy import features as F
from shortcircuit.strategy.back_to_vwap import BackToVWAPShort
from shortcircuit.strategy.htf_confluence import HTFConfluence
from shortcircuit.strategy.market_context import MarketContext
from shortcircuit.strategy.market_profile import ProfileAnalyzer
from shortcircuit.strategy.top_coil import TopCoilShort

logger = logging.getLogger(__name__)

SIGNAL_LOG_FILE = "logs/signals.csv"

# Shared pool for the G9 higher-timeframe check. Sized for the scanner's parallel
# candidate analysis; daemon threads so it can never hold up interpreter shutdown.
_HTF_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="htf-confluence"
)


def log_signal(
    symbol: str,
    ltp: float,
    pattern: str,
    stop_loss: float,
    meta: str = "",
    setup_high: float = 0.0,
    tick_size: float = 0.05,
    atr: float = 0.0,
    stretch_score: float = 0.0,
    vol_fade_ratio: float = 0.0,
    confidence: str = "",
    pattern_bonus: str = "None",
    oi_direction: str = "unknown",
):
    """Persists signal details to a CSV file for EOD analysis."""
    os.makedirs(os.path.dirname(SIGNAL_LOG_FILE), exist_ok=True)
    file_exists = os.path.exists(SIGNAL_LOG_FILE)

    with open(SIGNAL_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                [
                    "timestamp",
                    "symbol",
                    "ltp",
                    "pattern",
                    "stop_loss",
                    "meta",
                    "setup_high",
                    "tick_size",
                    "atr",
                    "stretch_score",
                    "vol_fade_ratio",
                    "confidence",
                    "pattern_bonus",
                    "oi_direction",
                ]
            )

        writer.writerow(
            [
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                symbol,
                ltp,
                pattern,
                stop_loss,
                meta,
                setup_high,
                tick_size,
                atr,
                stretch_score,
                vol_fade_ratio,
                confidence,
                pattern_bonus,
                oi_direction,
            ]
        )


# 09:15 to 15:30 IST is 375 one-minute bars. Request the full session so the
# cumulative VWAP in features.enrich_dataframe() is anchored to the open rather
# than to wherever a truncated frame happens to begin.
SESSION_OPEN_IST = dtime(9, 15)
SESSION_BARS_1M = 400  # 375 + slack; the aggregator's deque holds 500
# Matches the validation gate's fixed 15-minute expiry, which every re-arm refreshes:
# inside it a re-qualifying coil is one continuing setup, not a new one.
TOPCOIL_EPISODE_GAP = datetime.timedelta(minutes=15)


def keep_session_only(df: pd.DataFrame, session: datetime.date) -> pd.DataFrame:
    """
    Return only `session`'s bars, deduplicated and in chronological order.

    BUG-2026-08-12, verified against the live API: a request with
    range_from == range_to == today for NSE:ORISSAMINE-EQ returned

        750 rows · 375 unique epochs · 303 fully duplicated rows
        is_monotonic_increasing = False · volume 1,193,078 vs a true ~594,000

    One session, but each bar roughly twice and out of order. The date filter
    alone cannot see this, which is why the dedupe and sort below exist.

    Measured impact, after checking rather than assuming: the duplication is
    block-structured — [session in order][session in order] — not interleaved.
    That makes most of it harmless. iloc[-1..-3] still land on the true last
    bars, and VWAP is Sum(tp*v)/Sum(v), so doubling both sides cancels exactly.
    G9 was tested on eight symbols and returned an identical verdict either way.

    What it does break is any bare sum of volume: 35,294,738 against a true
    17,647,369 on NSE:SBIN-EQ. The scanner is unaffected because it reads volume
    from quotes, not from history.

    So this normalisation is defensive rather than load-bearing today. It is kept
    because every consumer of this frame assumes one ordered session with no
    repeats, and if the duplication ever becomes interleaved instead of blocked,
    that assumption fails silently and everything above stops being true.

    The date filter is kept as well: Fyers documents cont_flag="1" as a
    continuous-contract flag that should be inert for an equity, so relying on
    the range being honoured is not safe either way.
    strategy/market_context.py already guarded its own fetch by date
    (`ts_ist.date() == today`), so half of this was known in one place and
    nowhere else.
    """
    if df is None or df.empty or "datetime" not in df.columns:
        return df

    original = len(df)
    out = df[df["datetime"].dt.date == session]

    # The same request returns each bar roughly twice and out of order (750 rows
    # for 375 epochs). Both effects are silent: volume double-counts, inflating
    # RVOL and the volume floor, and df.iloc[-1] is not the latest bar. Dedupe on
    # the timestamp keeping the last copy, then sort.
    if "epoch" in out.columns:
        out = out.drop_duplicates(subset="epoch", keep="last").sort_values("epoch")
    else:
        out = out.drop_duplicates(subset="datetime", keep="last").sort_values("datetime")

    if len(out) != original:
        logger.warning(
            "[HISTORY] broker returned %d bars → %d after same-session filter, "
            "dedupe and sort (%d sessions seen)",
            original,
            len(out),
            df["datetime"].dt.date.nunique(),
        )
    return out.reset_index(drop=True)


def frame_reaches_session_open(df: pd.DataFrame) -> bool:
    """
    True when the frame's first bar is at or before the session open, so a
    cumulative VWAP over it is the session VWAP.

    One minute of slack: the 09:15 bar can be stamped 09:15:00 or arrive as the
    first tick a few seconds later.
    """
    if df is None or df.empty or "datetime" not in df.columns:
        return False
    try:
        first = df["datetime"].iloc[0]
        return first.time() <= dtime(9, 16)
    except Exception:
        return False


class FyersAnalyzer:
    """
    Thin orchestrator: data fetch → enrich → pre-filter → strategy.evaluate() → finalize.
    """

    def __init__(self, fyers, broker=None, morning_high=None, morning_low=None):
        self.fyers = fyers
        self.broker = broker
        self.market_context = MarketContext(fyers, morning_high, morning_low, broker=broker)
        self.signal_manager = get_signal_manager()
        self.htf_confluence = HTFConfluence(fyers)
        self.profile_analyzer = ProfileAnalyzer()
        self.strategy = BackToVWAPShort()
        self.top_coil = TopCoilShort()
        # symbol -> (obs_id, last re-arm). A coil re-qualifies on every bar it
        # stays tight, so without this one JAYKAY setup on 23 Sep wrote 43 ML rows
        # and 43 signal-log lines, each graded as a separate 'missed trade'.
        self._topcoil_episodes: dict[str, tuple[str, datetime.datetime]] = {}

    # Data fetching

    def get_history(self, symbol: str, interval: str = "1") -> pd.DataFrame | None:
        """
        Fetch intraday historical data for a symbol.
        Prefers local candle aggregator (1-minute). Falls back to REST.
        """
        # Try the local aggregator first (1-minute only).
        #
        # enrich_dataframe computes a CUMULATIVE vwap over whatever frame it gets,
        # so the frame length IS the anchor. Asking for 100 bars makes C1 measure
        # against a rolling VWAP, not the session one: on 12 Aug NSE:ORISSAMINE-EQ
        # read 1.52 SD BELOW a VWAP it was actually above. The REST path below
        # always fetched from the open, so "VWAP" depended on which tier answered.
        # VWAP_ANCHOR_MODE now picks deliberately; the defect returns under ROLLING.
        _anchor = str(getattr(config, "VWAP_ANCHOR_MODE", "SESSION")).upper()
        _rolling = _anchor == "ROLLING"
        _bars = int(getattr(config, "VWAP_ROLLING_BARS", 100)) if _rolling else SESSION_BARS_1M

        if interval == "1" and getattr(config, "P82_LOCAL_CANDLES_ENABLED", False) and self.broker:
            local_candles = self.broker.get_local_candles(symbol, n=_bars)

            min_required = getattr(config, "RVOL_MIN_CANDLES", 15) + 3
            if local_candles and len(local_candles) >= min_required:
                data = []
                for c in local_candles:
                    data.append([c.epoch, c.open, c.high, c.low, c.close, c.volume])
                cols = ["epoch", "open", "high", "low", "close", "volume"]
                df = pd.DataFrame(data, columns=cols)
                df["datetime"] = (
                    pd.to_datetime(df["epoch"], unit="s")
                    .dt.tz_localize("UTC")
                    .dt.tz_convert("Asia/Kolkata")
                )

                # Bar count is necessary but not sufficient: the aggregator only
                # holds candles seen since process start, so after a mid-session
                # restart its VWAP is anchored at restart time. SESSION falls
                # through to REST for a true session anchor. ROLLING wants a
                # mid-session anchor, so falling through would silently restore
                # the tier-dependent split this flag exists to end.
                if _rolling:
                    return df

                if frame_reaches_session_open(df):
                    return df
                logger.debug(
                    "[HISTORY] %s local buffer starts %s, past the open — "
                    "using REST so VWAP stays session-anchored",
                    symbol,
                    df["datetime"].iloc[0].strftime("%H:%M"),
                )

        # 2. Fallback to REST
        today = datetime.date.today().strftime("%Y-%m-%d")
        data = {
            "symbol": symbol,
            "resolution": interval,
            "date_format": "1",
            "range_from": today,
            "range_to": today,
            "cont_flag": "1",
        }

        try:
            response = self.fyers.history(data=data)
            if "candles" in response and response["candles"]:
                cols = ["epoch", "open", "high", "low", "close", "volume"]
                df = pd.DataFrame(response["candles"], columns=cols)
                df["datetime"] = (
                    pd.to_datetime(df["epoch"], unit="s")
                    .dt.tz_localize("UTC")
                    .dt.tz_convert("Asia/Kolkata")
                )

                # The broker can return more than the requested range. A
                # cumulative VWAP computed over two sessions is anchored to
                # yesterday's open, which is worse than the rolling window this
                # path replaced.
                df = keep_session_only(df, datetime.date.today())
                if df is None or df.empty:
                    logger.warning("No same-day history for %s", symbol)
                    return None

                # Keep the anchor definition independent of which data tier
                # answered. Before 12 Aug the local path was rolling while this
                # one was session-anchored, so "VWAP" meant different things on
                # different scans of the same symbol — 295 of one session's 340
                # scans took the local path and the rest did not. Whatever
                # VWAP_ANCHOR_MODE says, it should say it here too.
                if _rolling and len(df) > _bars:
                    df = df.iloc[-_bars:].reset_index(drop=True)
                return df
            else:
                logger.warning(f"No history data for {symbol}")
                return None
        except Exception as e:
            logger.error(f"Error fetching history for {symbol}: {e}")
            return None

    # Main entry point

    def check_setup(
        self,
        symbol: str,
        ltp: float,
        oi: float = 0,
        pre_fetched_df: pd.DataFrame | None = None,
        df_15m: pd.DataFrame | None = None,
        scan_id: int = 0,
        data_tier: str = "UNKNOWN",
    ) -> dict[str, Any] | None:
        """
        Public API — called by main.py trading loop.
        Signature intentionally unchanged from the original for backward compat.
        """
        grl = get_gate_result_logger()
        gr = GateResult(symbol=symbol, scan_id=scan_id, data_tier=data_tier)
        signal_meta = {}

        # Data fetch
        df = pre_fetched_df.copy() if pre_fetched_df is not None else self.get_history(symbol)

        if df is None or df.empty:
            gr.verdict = "DATA_ERROR"
            gr.rejection_reason = "No history data available"
            grl.record(gr)
            return None

        # G2: Candle count guard
        if config.RVOL_VALIDITY_GATE_ENABLED and len(df) < config.RVOL_MIN_CANDLES:
            gr.g2_pass = False
            gr.g2_value = float(len(df))
            gr.verdict = "REJECTED"
            gr.first_fail_gate = "G2_RVOL_VALIDITY"
            gr.rejection_reason = (
                f"Only {len(df)} candles — need {config.RVOL_MIN_CANDLES} for valid RVOL"
            )
            logger.warning(
                "SKIP %s — RVOL_VALIDITY_GATE: Only %s candles — need %s",
                symbol,
                len(df),
                config.RVOL_MIN_CANDLES,
            )
            grl.record(gr)
            return None
        gr.g2_pass = True

        # Enrichment
        F.enrich_dataframe(df)
        prev_df = df.iloc[:-1]

        atr = F.compute_atr(df)
        vwap_sd = F.compute_vwap_sd(prev_df)
        slope_30m, _ = F.compute_vwap_slope(df.iloc[-30:], window=30)
        slope_5m, _ = F.compute_vwap_slope(df.iloc[-5:], window=5)

        # Decay trigger: fast slope drops below slow slope
        is_decaying = False
        decay_sd = 2.0
        if slope_5m < (slope_30m * 0.90) and vwap_sd > decay_sd:
            is_decaying = True
            logger.info(
                "⚡ [INFLECTION] %s Decaying: Fast(%.2f) < Slow(%.2f)",
                symbol,
                slope_5m,
                slope_30m,
            )

        # Gain calculation
        pc = 0
        try:
            if self.broker:
                snapshot = self.broker.get_quote_cache_snapshot()
                if symbol in snapshot:
                    entry = snapshot[symbol]
                    pc = entry.get("pc", 0)
                    if pc == 0 and entry.get("ch_oc", 0) != 0:
                        ltp_val = entry.get("ltp", ltp)
                        ch_oc = entry.get("ch_oc")
                        pc = ltp_val / (1 + (ch_oc / 100))
        except Exception:
            pass

        day_high = df["high"].max()
        open_price = df.iloc[0]["open"]
        baseline = pc if pc > 0 else open_price
        gain_pct = ((ltp - baseline) / baseline) * 100

        # Profile pre-calc
        profile = None
        profile_rejection = False
        try:
            profile = self.profile_analyzer.calculate_market_profile(df, mode="VOLUME")
            if profile:
                profile_rejection, _ = self.profile_analyzer.check_profile_rejection(df, ltp)
            self.market_context.get_volume_z_score(df)
        except Exception as e:
            logger.warning(f"Profile/VolZ pre-calc error for {symbol}: {e}")

        allowed, reason = self.market_context.is_safe_trade_window()
        gr.g7_pass = allowed
        gr.g7_value = reason
        if not allowed:
            gr.verdict = "REJECTED"
            gr.first_fail_gate = "G7_REGIME"
            gr.rejection_reason = reason
            grl.record(gr)
            return None

        # Pre-fetch depth for the strategy
        upper_circuit = 0.0
        lower_circuit = 0.0
        spread_pct = 0.0
        is_circuit_hitter = False
        try:
            # One call per candidate, run concurrently across a scan — easily a
            # dozen in the same second. Unmetered, that alone could exceed the
            # whole per-second budget and starve the order path of the headroom
            # the limiter believed it was reserving.
            rest_limiter.acquire()
            full_depth = self.fyers.depth(data={"symbol": symbol, "ohlcv_flag": "1"})
            if "d" in full_depth and symbol in full_depth["d"]:
                depth_data = full_depth["d"][symbol]
                upper_circuit = depth_data.get("upper_ckt", 0)
                lower_circuit = depth_data.get("lower_ckt", 0)

                if upper_circuit > 0 and ltp >= upper_circuit * 0.999:
                    self.market_context.mark_circuit_touched(symbol)

                # Spread
                ask = depth_data["ask"][0]["price"] if depth_data.get("ask") else ltp
                bid = depth_data["bid"][0]["price"] if depth_data.get("bid") else ltp
                if ltp > 0:
                    spread_pct = (ask - bid) / ltp

        except Exception as depth_err:
            # Deliberately non-fatal, but no longer silent. When this fails
            # upper_circuit stays 0.0, and C0's circuit branch is `if upper_circuit
            # > 0`, so the guard against shorting into a limit-up move is skipped
            # for this evaluation. SCANNER_GAIN_MAX_PCT is the backstop; this log
            # is what makes the gap measurable rather than invisible.
            logger.warning(
                "[DEPTH] %s unavailable (%s) — circuit and spread checks skipped "
                "this pass; only the gain ceiling is protecting the entry",
                symbol,
                depth_err,
            )

        if upper_circuit <= 0:
            logger.debug("[DEPTH] %s no upper_ckt — C0 circuit branch inactive", symbol)

        is_circuit_hitter = self.market_context.is_circuit_hitter(symbol)

        # Strategy evaluation, replacing gates G1-G6.
        # BACKTOVWAP_ENABLED is the master switch for the primary detector. When it
        # is False the bot runs on TopCoilShort alone — note that back_to_vwap's own
        # C0 pre-filters (gain floor, circuit proximity, spread) go quiet with it,
        # which is why TopCoilShort carries its own TC0 equivalents.
        result = None
        if getattr(config, "BACKTOVWAP_ENABLED", True):
            result = self.strategy.evaluate(
                symbol=symbol,
                ltp=ltp,
                df=df,
                profile=profile,
                profile_rejection=profile_rejection,
                vwap_sd=vwap_sd,
                atr=atr,
                gain_pct=gain_pct,
                slope_fast=slope_5m,
                slope_slow=slope_30m,
                is_decaying=is_decaying,
                upper_circuit=upper_circuit,
                lower_circuit=lower_circuit,
                spread_pct=spread_pct,
                is_circuit_hitter=is_circuit_hitter,
            )

        # Second detector. It runs ONLY on symbols the primary strategy has already
        # turned down, so it can never loosen an existing gate — it can only add
        # setups C1 is structurally incapable of seeing (a coil at the high clears
        # the 3.2 SD floor 0.31% of the time). Everything downstream of here — G9
        # HTF confluence, G8 cooldown and daily target, depth and circuit checks —
        # applies to it unchanged.
        is_top_coil = False
        if result is None and getattr(config, "TOPCOIL_ENABLED", False):
            try:
                result = self.top_coil.evaluate(
                    symbol=symbol,
                    ltp=ltp,
                    df=df,
                    gain_pct=gain_pct,
                    spread_pct=spread_pct,
                    upper_circuit=upper_circuit,
                    lower_circuit=lower_circuit,
                    is_circuit_hitter=is_circuit_hitter,
                )
            except Exception as tc_err:
                # Fail closed and keep the primary verdict. A detector that is not
                # yet trusted must never be able to take the process down with it.
                logger.error("[TOPCOIL] %s evaluate raised: %s", symbol, tc_err)
                result = None
            is_top_coil = result is not None

        if result is None:
            gr.g5_pass = False
            gr.verdict = "REJECTED"
            gr.first_fail_gate = "G5_STRATEGY"
            gr.rejection_reason = (
                "No detector matched"
                if getattr(config, "TOPCOIL_ENABLED", False)
                else "BackToVWAPShort conditions not met"
            )
            grl.record(gr)
            return None

        gr.g5_pass = True
        gr.g5_value = round(result.get("stretch_score", 0), 3)
        gr.g6_pass = True
        gr.g6_value = f"+{result['confidence']}"

        signal_meta.update(result)
        pattern_desc = result.get("pattern_bonus", "EXHAUSTION_FADE")

        # G9: HTF confluence, on a shared long-lived pool. A per-symbol
        # ThreadPoolExecutor used as a context manager would block here on
        # shutdown(wait=True), defeating the very timeout below.
        try:
            _htf_future = _HTF_EXECUTOR.submit(
                self.htf_confluence.check_trend_exhaustion,
                symbol,
                df_15m=df_15m,
                vwap_sd=vwap_sd,
            )
            htf_ok, htf_msg = _htf_future.result(timeout=1.5)
        except concurrent.futures.TimeoutError:
            # Abandon the worker rather than waiting on it; G9 is fail-closed.
            htf_ok, htf_msg = False, "G9 BLOCK: HTF check timed out (1.5s)"
        except Exception as e:
            htf_ok, htf_msg = False, f"G9 BLOCK: {e}"

        gr.g9_pass = htf_ok
        gr.g9_value = htf_msg

        if not htf_ok:
            gr.verdict = "REJECTED"
            gr.first_fail_gate = "G9_HTF_CONFLUENCE"
            gr.rejection_reason = f"HTF blocked: {htf_msg}"
            grl.record(gr)
            return None

        # G8: Signal Manager (cooldown + daily target)
        sm = self.signal_manager
        confidence = signal_meta.get("confidence", "")
        can_signal, sm_reason = (
            sm.can_signal(symbol, confidence=confidence)
            if hasattr(sm, "can_signal")
            else (True, "")
        )

        gr.g8_pass = can_signal
        gr.g8_value = None
        if not can_signal:
            gr.verdict = "REJECTED"
            gr.first_fail_gate = "G8_SIGNAL_MANAGER"
            gr.rejection_reason = sm_reason
            grl.record(gr)
            return None

        # Reward/risk: a smaller target multiple on weaker moves.
        if is_top_coil:
            pass  # EOD_HOLD carries no take-profit for a multiple to scale
        elif gain_pct < 9.0:
            signal_meta["tp_atr_mult_override"] = 0.5
        else:
            signal_meta["tp_atr_mult_override"] = 1.0

        # TopCoilShort sets snapshot_high to the COIL high, which is what the stop
        # was measured against. It sits at or below the day high by construction,
        # so overwriting it here would silently widen every top-coil stop.
        if not is_top_coil:
            signal_meta["snapshot_high"] = day_high

        # Finalize
        gr.verdict = "ANALYZER_PASS"
        finalized = self._finalize_signal(symbol, ltp, df, pattern_desc, slope_5m, "", signal_meta)
        if finalized:
            finalized["_gate_result"] = gr
        else:
            gr.verdict = "DATA_ERROR"

        grl.record(gr)
        return finalized

    # Private helpers

    def _finalize_signal(
        self,
        symbol,
        ltp,
        df,
        pattern_desc,
        slope,
        wall_msg,
        signal_meta: dict = None,
    ):
        """Calculates SL, builds signal dict, logs to CSV and ML. Pure — no gate checks."""
        if signal_meta is None:
            signal_meta = {}

        # Calculate Stop Loss (ATR-based)
        atr = F.compute_atr(df)
        buffer = max(atr * 0.5, 0.25)

        # Use absolute high snapshot for SL
        peak_high = signal_meta.get("snapshot_high", df.iloc[-2]["high"])
        setup_high = peak_high
        sl_price = setup_high + buffer

        # A top-coil re-arm inside the validation gate's 15-minute window is the
        # SAME setup with a refreshed trigger, not a new signal. It keeps its first
        # observation and only moves the levels on it.
        is_top_coil = signal_meta.get("exit_profile") == "EOD_HOLD"
        now_ist = datetime.datetime.now()
        rearm_obs = None
        if is_top_coil:
            prev = self._topcoil_episodes.get(symbol)
            if prev and now_ist - prev[1] <= TOPCOIL_EPISODE_GAP:
                rearm_obs = prev[0]
                self._topcoil_episodes[symbol] = (rearm_obs, now_ist)

        # Logging
        logger.info(f"[OK] SIGNAL: {symbol} | {pattern_desc}" + (" (re-arm)" if rearm_obs else ""))

        meta_str = f"Slope:{slope:.1f}, ATR:{atr:.2f}"
        if rearm_obs is None:
            log_signal(
                symbol,
                ltp,
                pattern_desc,
                sl_price,
                meta_str,
                setup_high=setup_high,
                tick_size=signal_meta.get("tick_size", 0.05),
                atr=atr,
                stretch_score=signal_meta.get("stretch_score", 0.0),
                vol_fade_ratio=signal_meta.get("vol_fade_ratio", 0.0),
                confidence=signal_meta.get("confidence", ""),
                pattern_bonus=signal_meta.get("pattern_bonus", "None"),
                oi_direction=signal_meta.get("oi_direction", "unknown"),
            )

        # Calculate VWAP for both ML logging and TP targeting
        vwap = df["vwap"].iloc[-1] if "vwap" in df.columns else ltp

        # Levels a ghost audit needs to grade a top-coil setup the way the engine
        # trades it: enter only if the trigger breaks, then stop or 15:10.
        topcoil_fields = (
            {
                "exit_profile": "EOD_HOLD",
                "trigger_price": signal_meta.get("signal_low_override"),
                "coil_high": signal_meta.get("coil_high"),
                "sl_price": sl_price,
                "armed_at": now_ist.isoformat(timespec="seconds"),
            }
            if is_top_coil
            else {}
        )

        # ML Data Logging
        obs_id = None
        if rearm_obs is not None:
            obs_id = rearm_obs
            try:
                get_ml_logger().update_fields(rearm_obs, **topcoil_fields)
            except Exception as e:
                logger.warning(f"   [ML] Re-arm update error: {e}")
        else:
            try:
                ml_logger = get_ml_logger()
                prev_candle = df.iloc[-2]

                body = abs(prev_candle["close"] - prev_candle["open"])
                total_range = prev_candle["high"] - prev_candle["low"]
                upper_wick = prev_candle["high"] - max(prev_candle["open"], prev_candle["close"])
                lower_wick = min(prev_candle["open"], prev_candle["close"]) - prev_candle["low"]

                vwap_dist = ((ltp - vwap) / vwap) * 100 if vwap > 0 else 0

                vol_avg = df["volume"].iloc[-20:].mean() if len(df) > 20 else df["volume"].mean()
                rvol = prev_candle["volume"] / vol_avg if vol_avg > 0 else 1

                features = {
                    "prev_close": df.iloc[0]["open"],
                    "day_high": df["high"].max(),
                    "day_low": df["low"].min(),
                    "gain_pct": ((ltp - df.iloc[0]["open"]) / df.iloc[0]["open"]) * 100,
                    "vwap": vwap,
                    "vwap_distance_pct": vwap_dist,
                    "vwap_sd": F.compute_vwap_sd(df.iloc[:-1]),
                    "vwap_slope": slope,
                    "volume_current": prev_candle["volume"],
                    "volume_avg_20": vol_avg,
                    "rvol": rvol,
                    "pattern": pattern_desc.split(" + ")[0],
                    "candle_body_pct": (body / total_range * 100) if total_range > 0 else 0,
                    "upper_wick_pct": (upper_wick / total_range * 100) if total_range > 0 else 0,
                    "lower_wick_pct": (lower_wick / total_range * 100) if total_range > 0 else 0,
                    "stretch_score": signal_meta.get("stretch_score", 0.0),
                    "vol_fade_ratio": signal_meta.get("vol_fade_ratio", 0.0),
                    "confidence": signal_meta.get("confidence", "MEDIUM"),
                    "pattern_bonus": signal_meta.get("pattern_bonus", "None"),
                    "num_confirmations": pattern_desc.count(",") + 1 if "+" in pattern_desc else 0,
                    "confirmations": pattern_desc.split(" + ")[1:] if " + " in pattern_desc else [],
                    "nifty_trend": (
                        self.market_context.get_trend_label()
                        if hasattr(self.market_context, "get_trend_label")
                        else "UNKNOWN"
                    ),
                    "atr": atr,
                    "sl_price": sl_price,
                    # EOD_HOLD has no target; a VWAP figure here made the ghost audit
                    # grade top-coil setups against an exit they never use.
                    "tp_price": None if is_top_coil else vwap,
                    "direction": getattr(config, "TRADE_DIRECTION", "SHORT"),
                    "leverage": getattr(config, "INTRADAY_LEVERAGE", 5.0),
                    **topcoil_fields,
                }

                obs_id = ml_logger.log_observation(symbol, ltp, features)
                logger.info(f"   [ML] Logged observation: {obs_id}")
                if is_top_coil and obs_id:
                    self._topcoil_episodes[symbol] = (obs_id, now_ist)
            except Exception as e:
                logger.warning(f"   [ML] Logging error: {e}")

        # Build signal dict
        signal_data = {
            "symbol": symbol,
            "ltp": ltp,
            "pattern": pattern_desc,
            "stop_loss": sl_price,
            "day_high": df["high"].max(),
            "signal_low": df.iloc[-2]["low"],
            "setup_high": setup_high,
            "signal_high": setup_high,
            "tick_size": signal_meta.get("tick_size", 0.05),
            "atr": atr,
            "vwap": vwap,
            "meta": meta_str,
            "obs_id": obs_id,
            "leverage": getattr(config, "INTRADAY_LEVERAGE", 5.0),
        }

        # Quality fields
        signal_data["stretch_score"] = signal_meta.get("stretch_score", 0.0)
        signal_data["vol_fade_ratio"] = signal_meta.get("vol_fade_ratio", 0.0)
        signal_data["confidence"] = signal_meta.get("confidence", "")
        signal_data["pattern_bonus"] = signal_meta.get("pattern_bonus", "None")
        signal_data["oi_direction"] = signal_meta.get("oi_direction", "unknown")

        # TP scaling override
        if "tp_atr_mult_override" in signal_meta:
            signal_data["tp_atr_mult_override"] = signal_meta["tp_atr_mult_override"]

        # Exit profile. Absent means the engine default (SCALE TP + time stop);
        # 'EOD_HOLD' means no ladder and no time stop, run to the 15:10 square-off.
        if signal_meta.get("exit_profile"):
            signal_data["exit_profile"] = signal_meta["exit_profile"]
        for _k in ("coil_high", "coil_low", "trigger_price"):
            if _k in signal_meta:
                signal_data[_k] = signal_meta[_k]

        # The validation gate watches signal_low at 5Hz and enters the moment price
        # crosses it. TopCoilShort wants that level to be the coil low, not the
        # previous bar's low: entering AT the level instead of after a confirming
        # 1-minute close is worth 0.23pp per trade (-0.070% vs -0.302% over 211
        # and 165 trades respectively), because by the close price is already
        # through it and the stop is correspondingly wider.
        if signal_meta.get("signal_low_override"):
            signal_data["signal_low"] = float(signal_meta["signal_low_override"])

        return signal_data
