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
strategy/top_coil.py — TopCoilShort.

Thesis (the operator's): a stock that has already pumped hard, then goes quiet in
a tight range AT its high, is distributing. Short the break below that range.

This is NOT BackToVWAPShort with different numbers — it is the opposite detector.
C1 wants price stretched away from VWAP; a coil is price letting VWAP catch up.
Measured over 19,587 bars of real signal-day data, a range tighter than 1% sitting
within 1.5% of the day's high clears the 3.2 SD floor 0.31% of the time. The gate
stack cannot see this setup, which is why this runs beside it rather than inside it.

WHAT THIS DETECTOR RETURNS, AND WHY IT MATTERS MORE THAN THE PATTERN
--------------------------------------------------------------------
It fires when the coil QUALIFIES, not when it breaks, and hands the engine a
trigger level (`signal_low`). The validation gate in focus_engine then watches at
5Hz and enters intrabar the moment price crosses it.

That is not a style choice. Measured on the same 997 stock-days, same coil, same
stop, same hold:

    trigger intrabar at the coil low        -0.070% / trade   (n=211)
    wait for a 1-minute bar to CLOSE below  -0.302% / trade   (n=165)

A close-confirmed entry gives up 0.23 percentage points, because by the time the
bar closes, price is already through the level — median risk goes from 1.69% to
1.83% and the fill is worse. The first version of this file waited for the close
and was rewritten for exactly this reason. Do not "simplify" it back.

MEASURED EXPECTANCY — READ THIS BEFORE ENABLING
------------------------------------------------
997 stock-days, Jun–Sep 2026, 0.212% entry slippage plus 0.106% statutory cost,
stop above the coil high, held to the 15:10 square-off, simulating the engine's
own validation gate (20-minute stale flush, invalidation on an upside break):

    gain floor   n     mean/trade   t       bootstrap 95% CI
    10.0        262     -0.223%   -1.42     [-0.518, +0.092]
    11.0        211     -0.070%   -0.37     [-0.423, +0.305]
    12.0        181     -0.124%   -0.60     [-0.517, +0.294]
    13.0        144     -0.004%   -0.02     [-0.434, +0.460]
    14.0        112     -0.124%   -0.52     [-0.573, +0.357]

Every cell is negative. Every interval contains zero. At an 11% floor June's 11
trades (+1.37% each) carry the whole series and July, August and September are
each negative on their own. This is a flat-to-slightly-losing strategy that the
operator has chosen to run, not a proven edge, and this docstring should keep
saying so until a live sample says otherwise.

The pattern reading behind it IS sound — above ~12% gain a coil at the high has an
up/down excursion ratio of 0.82, and 0.56/0.60/0.59 across three separate months
above 15%. The tilt is real. It is simply smaller than 0.318% of round-trip
friction, which is the same wall six other entry rules have hit here.
"""

import logging
from typing import Any

import pandas as pd
import shortcircuit.config as cfg

logger = logging.getLogger(__name__)


class TopCoilShort:
    """Coil-at-the-high detector. Stateless: the coil is re-derived from the frame
    on every call, so there is no per-symbol arming state to leak between sessions
    or go stale across a restart. Arming, invalidation and expiry are the
    validation gate's job, and it already does all three."""

    def evaluate(
        self,
        symbol: str,
        ltp: float,
        df: pd.DataFrame,
        gain_pct: float,
        spread_pct: float = 0.0,
        upper_circuit: float = 0.0,
        lower_circuit: float = 0.0,
        is_circuit_hitter: bool = False,
    ) -> dict[str, Any] | None:
        """Returns a signal_meta dict when a tradeable coil is sitting at the high,
        else None. The break itself is the engine's trigger, not this method's."""

        # Shared risk pre-filters. These are not part of the pattern; they are the
        # same C0 guards BackToVWAPShort runs, and a second detector must not
        # become a way around them.
        if is_circuit_hitter:
            logger.debug("  [TC0] %s REJECT: circuit hitter", symbol)
            return None
        if upper_circuit > 0 and ltp >= upper_circuit * 0.985:
            logger.debug("  [TC0] %s REJECT: near upper circuit", symbol)
            return None
        if lower_circuit > 0 and ltp <= lower_circuit * 1.005:
            logger.debug("  [TC0] %s REJECT: near lower circuit", symbol)
            return None
        if spread_pct > 0.004:
            logger.debug("  [TC0] %s REJECT: spread %.4f", symbol, spread_pct)
            return None

        gmin = float(getattr(cfg, "TOPCOIL_GAIN_MIN_PCT", 11.0))
        gmax = float(getattr(cfg, "TOPCOIL_GAIN_MAX_PCT", 30.0))
        if not (gmin <= gain_pct <= gmax):
            logger.debug(
                "  [TC1] %s REJECT: gain %.1f%% outside [%.1f, %.1f]",
                symbol,
                gain_pct,
                gmin,
                gmax,
            )
            return None

        setup = self.find_setup(df)
        if setup is None:
            return None

        logger.info(
            "✅ [TOPCOIL] %s coil %.2f–%.2f at the high | gain %.1f%% | arming trigger < ₹%.2f",
            symbol,
            setup["coil_low"],
            setup["coil_high"],
            gain_pct,
            setup["trigger_price"],
        )

        return {
            "confidence": "MEDIUM",
            "pattern_bonus": "TOP_COIL_BREAKDOWN",
            "stretch_score": 0.0,
            "vol_fade_ratio": 0.0,
            # The stop belongs above the COIL high, not the day high. They sit
            # within 1.5% of each other by construction, but when the coil forms
            # off a slightly lower high this is the tighter, correct one.
            "snapshot_high": setup["coil_high"],
            "coil_high": setup["coil_high"],
            "coil_low": setup["coil_low"],
            # Overrides the default signal_low (the previous bar's low). This is
            # the level the validation gate watches at 5Hz, and entering AT it
            # rather than after a confirming close is worth 0.23pp per trade.
            "signal_low_override": setup["trigger_price"],
            "trigger_price": setup["trigger_price"],
            # Read by order_manager and focus_engine: no take-profit ladder and no
            # 45-minute time stop, run to the 15:10 square-off. Every exit variant
            # that cut the trade short scored worse across the whole sweep grid.
            "exit_profile": "EOD_HOLD",
        }

    # Internal

    @staticmethod
    def find_setup(df: pd.DataFrame) -> dict[str, Any] | None:
        """
        Is the most recent completed bar the end of a tight coil at the day's high?

        Operates on completed candles only. The final row of a live frame is the
        bar still forming, whose high and low are not yet settled; including it
        would let a single spike widen the range and disqualify a real coil, or
        let a forming dip qualify one that has already broken.

        Deliberately does NOT look for the break. The research harness that tested
        the coil and the break on one window found 0 setups in 997 stock-days —
        the breaking bar widens the range, so the window fails its own tightness
        test. Here the engine's validation gate watches for the break instead,
        which separates the two by construction and gets the better fill.
        """
        bars = int(getattr(cfg, "TOPCOIL_COIL_BARS", 15))
        near = float(getattr(cfg, "TOPCOIL_NEAR_HOD_PCT", 1.5)) / 100.0
        mrange = float(getattr(cfg, "TOPCOIL_MAX_RANGE_PCT", 2.0)) / 100.0
        bbuf = float(getattr(cfg, "TOPCOIL_BREAK_BUFFER_PCT", 0.1)) / 100.0
        first = int(getattr(cfg, "TOPCOIL_FIRST_MIN", 585))
        last = int(getattr(cfg, "TOPCOIL_LAST_MIN", 880))

        if df is None or len(df) < bars + 2:
            return None
        if "datetime" not in df.columns:
            return None

        d = df.iloc[:-1]  # drop the forming bar
        if len(d) < bars:
            return None

        last_bar = d.iloc[-1]
        minute = int(last_bar["datetime"].hour) * 60 + int(last_bar["datetime"].minute)
        if minute < first:
            return None  # no profile to coil against yet
        if minute > last:
            return None  # no room left before the square-off

        window = d.iloc[-bars:]
        coil_high = float(window["high"].max())
        coil_low = float(window["low"].min())
        close = float(last_bar["close"])
        if coil_low <= 0 or close <= 0:
            return None

        hod = float(d["high"].max())
        if coil_high < hod * (1 - near):  # the range must sit AT the high
            return None
        if (coil_high - coil_low) / close > mrange:  # and be tight
            return None

        trigger = coil_low * (1 - bbuf)
        if close <= trigger:
            # Already through the level. Arming now would have the gate fire
            # instantly at a price the research never entered at.
            return None

        return {
            "coil_low": coil_low,
            "coil_high": coil_high,
            "trigger_price": trigger,
        }
