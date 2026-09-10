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
Option Chain Feature Engine
────────────────────────────
Computes PCR, OI skew, IV, max pain, and other option chain features
from existing option candle data in minute_candles table.

These features fill in the 14 all-NaN columns in the macro feature set:
  pcr, oi_change, iv, days_to_expiry, theta_pressure, oi_skew,
  pcr_near_atm, pcr_far, max_oi_call_rel, max_oi_put_rel,
  oi_concentration, call_oi_gradient, put_oi_gradient, iv_skew

Usage:
  from features.option_chain_features import OptionChainFeatureEngine
  engine = OptionChainFeatureEngine()
  features = engine.compute_for_timestamp(timestamp, spot_price)
"""

import math
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from utils.logger import get_logger

from database.db import read_sql

logger = get_logger("option_chain_features")

# NIFTY strike gap
STRIKE_GAP = 50
# Number of strikes around ATM to consider "near ATM"
NEAR_ATM_STRIKES = 3
# Number of strikes beyond near ATM for "far" OTM
FAR_OTM_STRIKES = 7


def parse_option_symbol(symbol: str) -> dict | None:
    """
    Parse a NIFTY option symbol like 'NIFTY26031723500PE' into components.
    Returns: {underlying, expiry_date, strike, option_type} or None
    """
    match = re.match(r"^(NIFTY|BANKNIFTY)(\d{2})(\d{2})(\d{2})(\d+)(CE|PE)$", symbol)
    if not match:
        return None

    underlying = match.group(1)
    yy = int(match.group(2))
    mm = int(match.group(3))
    dd = int(match.group(4))
    strike = float(match.group(5))
    option_type = match.group(6)

    try:
        expiry_date = date(2000 + yy, mm, dd)
    except ValueError:
        return None

    return {
        "underlying": underlying,
        "expiry_date": expiry_date,
        "strike": strike,
        "option_type": option_type,
    }


def compute_atm_strike(spot_price: float, gap: int = STRIKE_GAP) -> float:
    """Round spot price to nearest strike."""
    return round(spot_price / gap) * gap


def estimate_iv_from_premium(
    premium: float, spot: float, strike: float, days_to_expiry: float, option_type: str, risk_free: float = 0.065
) -> float:
    """
    Quick IV estimate using simplified Black-Scholes inversion.
    Uses bisection method for reasonable accuracy without scipy.
    """
    if premium <= 0 or days_to_expiry <= 0 or spot <= 0:
        return 0.0

    T = days_to_expiry / 365.0

    def bs_price(sigma):
        """Simplified BS price."""
        if sigma <= 0:
            return 0
        d1 = (math.log(spot / strike) + (risk_free + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        # Use normal CDF approximation
        from math import erf

        nd1 = 0.5 * (1 + erf(d1 / math.sqrt(2)))
        nd2 = 0.5 * (1 + erf(d2 / math.sqrt(2)))
        if option_type == "CE":
            return spot * nd1 - strike * math.exp(-risk_free * T) * nd2
        return strike * math.exp(-risk_free * T) * (1 - nd2) - spot * (1 - nd1)

    # Bisection
    lo, hi = 0.01, 5.0
    for _ in range(50):
        mid = (lo + hi) / 2
        price = bs_price(mid)
        if price > premium:
            hi = mid
        else:
            lo = mid
        if abs(price - premium) < 0.01:
            break

    return (lo + hi) / 2


class OptionChainFeatureEngine:
    """Computes option chain features from minute_candles option data."""

    def __init__(self):
        self._cache = {}

    def _get_option_symbols_for_date(self, target_date: date) -> list[str]:
        """Find all option symbols that have data for a given date."""
        cache_key = f"symbols_{target_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        df = read_sql(
            """
            SELECT DISTINCT symbol FROM minute_candles
            WHERE symbol LIKE :pat
            AND symbol ~ '[0-9]+(CE|PE)$'
            AND timestamp::date = :dt
            """,
            {"pat": "NIFTY%", "dt": str(target_date)},
        )
        symbols = df["symbol"].tolist() if not df.empty else []
        self._cache[cache_key] = symbols
        return symbols

    def _load_option_data_at_time(
        self,
        target_date: date,
        timestamp: pd.Timestamp,
    ) -> pd.DataFrame:
        """Load the latest option candle data at or before a given timestamp."""
        cache_key = f"data_{target_date}"
        if cache_key not in self._cache:
            # Load all option data for the day in one query
            data = read_sql(
                """
                SELECT timestamp, symbol, close, volume, oi
                FROM minute_candles
                WHERE symbol LIKE :pat
                AND symbol ~ '[0-9]+(CE|PE)$'
                AND timestamp::date = :dt
                ORDER BY timestamp
                """,
                {"pat": "NIFTY%", "dt": str(target_date)},
            )
            if not data.empty:
                data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
            self._cache[cache_key] = data

        all_data = self._cache[cache_key]
        if all_data.empty:
            return pd.DataFrame()

        # Ensure timestamp is tz-aware for comparison
        ts = pd.Timestamp(timestamp)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")

        # Get latest row per symbol at or before the timestamp
        mask = all_data["timestamp"] <= ts
        filtered = all_data[mask]
        if filtered.empty:
            return pd.DataFrame()

        # Keep latest per symbol
        return filtered.groupby("symbol").last().reset_index()

    def compute_for_timestamp(
        self,
        timestamp: pd.Timestamp,
        spot_price: float,
    ) -> dict[str, float]:
        """
        Compute all option chain features for a given timestamp and spot price.

        Returns dict with keys matching the NaN feature columns:
            pcr, oi_change, iv, days_to_expiry, theta_pressure,
            oi_skew, pcr_near_atm, pcr_far, max_oi_call_rel,
            max_oi_put_rel, oi_concentration, call_oi_gradient,
            put_oi_gradient, iv_skew
        """
        target_date = timestamp.date() if hasattr(timestamp, "date") else timestamp
        if isinstance(target_date, pd.Timestamp):
            target_date = target_date.date()

        # Default NaN features
        defaults = {
            "pcr": np.nan,
            "oi_change": np.nan,
            "iv": np.nan,
            "days_to_expiry": np.nan,
            "theta_pressure": np.nan,
            "oi_skew": np.nan,
            "pcr_near_atm": np.nan,
            "pcr_far": np.nan,
            "max_oi_call_rel": np.nan,
            "max_oi_put_rel": np.nan,
            "oi_concentration": np.nan,
            "call_oi_gradient": np.nan,
            "put_oi_gradient": np.nan,
            "iv_skew": np.nan,
            "relative_strike": np.nan,
        }

        option_data = self._load_option_data_at_time(target_date, timestamp)
        if option_data.empty:
            return defaults

        # Parse symbols and enrich with strike/type info
        parsed = []
        for _, row in option_data.iterrows():
            info = parse_option_symbol(row["symbol"])
            if info is None:
                continue
            info.update(
                {
                    "symbol": row["symbol"],
                    "close": row["close"],
                    "volume": row.get("volume", 0),
                    "oi": row.get("oi", 0),
                }
            )
            parsed.append(info)

        if not parsed:
            return defaults

        df = pd.DataFrame(parsed)
        atm_strike = compute_atm_strike(spot_price)

        # Relative strike (0=ATM, +1=ATM+1, etc.)
        df["relative_strike"] = ((df["strike"] - atm_strike) / STRIKE_GAP).astype(int)

        # Separate CE and PE
        calls = df[df["option_type"] == "CE"].copy()
        puts = df[df["option_type"] == "PE"].copy()

        if calls.empty or puts.empty:
            return defaults

        # Find nearest expiry
        expiries = sorted(df["expiry_date"].unique())
        # Filter to expiries that haven't passed
        future_expiries = [e for e in expiries if e >= target_date] if isinstance(target_date, date) else expiries
        nearest_expiry = future_expiries[0] if future_expiries else expiries[-1]

        # Filter to nearest expiry only
        calls_ne = calls[calls["expiry_date"] == nearest_expiry]
        puts_ne = puts[puts["expiry_date"] == nearest_expiry]

        if calls_ne.empty or puts_ne.empty:
            # Fallback to all expiries
            calls_ne = calls
            puts_ne = puts

        # ── Days to expiry ──────────────────────────────────────────
        dte = (nearest_expiry - target_date).days if isinstance(target_date, date) else 5
        dte = max(dte, 0)

        # ── PCR (Put-Call Ratio by OI) ──────────────────────────────
        total_call_oi = calls_ne["oi"].sum()
        total_put_oi = puts_ne["oi"].sum()
        pcr = total_put_oi / max(total_call_oi, 1)

        # ── PCR near ATM (±3 strikes) ──────────────────────────────
        near_calls = calls_ne[calls_ne["relative_strike"].abs() <= NEAR_ATM_STRIKES]
        near_puts = puts_ne[puts_ne["relative_strike"].abs() <= NEAR_ATM_STRIKES]
        pcr_near = near_puts["oi"].sum() / max(near_calls["oi"].sum(), 1)

        # ── PCR far OTM ────────────────────────────────────────────
        far_calls = calls_ne[calls_ne["relative_strike"] > NEAR_ATM_STRIKES]
        far_puts = puts_ne[puts_ne["relative_strike"] < -NEAR_ATM_STRIKES]
        pcr_far = far_puts["oi"].sum() / max(far_calls["oi"].sum(), 1)

        # ── OI Change (total OI sum as proxy) ──────────────────────
        oi_change = total_call_oi + total_put_oi

        # ── Max OI strikes (relative to ATM) ───────────────────────
        max_oi_call_strike = calls_ne.loc[calls_ne["oi"].idxmax(), "relative_strike"] if not calls_ne.empty else 0
        max_oi_put_strike = puts_ne.loc[puts_ne["oi"].idxmax(), "relative_strike"] if not puts_ne.empty else 0

        # ── OI Skew: (put OI at ATM - call OI at ATM) / total ─────
        atm_calls = calls_ne[calls_ne["relative_strike"] == 0]
        atm_puts = puts_ne[puts_ne["relative_strike"] == 0]
        atm_call_oi = atm_calls["oi"].sum() if not atm_calls.empty else 0
        atm_put_oi = atm_puts["oi"].sum() if not atm_puts.empty else 0
        total_oi = max(total_call_oi + total_put_oi, 1)
        oi_skew = (atm_put_oi - atm_call_oi) / total_oi

        # ── OI Concentration: top 3 strikes OI / total OI ─────────
        top3_call_oi = calls_ne.nlargest(3, "oi")["oi"].sum()
        top3_put_oi = puts_ne.nlargest(3, "oi")["oi"].sum()
        oi_concentration = (top3_call_oi + top3_put_oi) / total_oi

        # ── OI Gradient: slope of OI across strikes ───────────────
        def oi_gradient(df_side):
            if len(df_side) < 3:
                return 0.0
            sorted_df = df_side.sort_values("strike")
            strikes = sorted_df["relative_strike"].values.astype(float)
            ois = sorted_df["oi"].values.astype(float)
            if len(strikes) > 1 and np.std(strikes) > 0:
                return float(np.polyfit(strikes, ois, 1)[0])
            return 0.0

        call_oi_grad = oi_gradient(calls_ne)
        put_oi_grad = oi_gradient(puts_ne)

        # ── IV estimation (ATM option) ─────────────────────────────
        atm_call_prem = atm_calls["close"].mean() if not atm_calls.empty else 0
        atm_put_prem = atm_puts["close"].mean() if not atm_puts.empty else 0

        iv_call = (
            estimate_iv_from_premium(atm_call_prem, spot_price, atm_strike, max(dte, 1), "CE")
            if atm_call_prem > 0
            else 0
        )

        iv_put = (
            estimate_iv_from_premium(atm_put_prem, spot_price, atm_strike, max(dte, 1), "PE") if atm_put_prem > 0 else 0
        )

        iv_avg = (iv_call + iv_put) / 2 if (iv_call > 0 and iv_put > 0) else max(iv_call, iv_put)

        # ── IV Skew: (put IV - call IV) ───────────────────────────
        iv_skew = iv_put - iv_call

        # ── Theta pressure: premium decay per day ──────────────────
        # Approximate: ATM premium / DTE
        atm_avg_prem = (atm_call_prem + atm_put_prem) / 2
        theta_pressure = atm_avg_prem / max(dte, 1) if atm_avg_prem > 0 else 0

        return {
            "pcr": round(pcr, 4),
            "oi_change": oi_change,
            "iv": round(iv_avg, 4),
            "days_to_expiry": dte,
            "theta_pressure": round(theta_pressure, 2),
            "oi_skew": round(oi_skew, 6),
            "pcr_near_atm": round(pcr_near, 4),
            "pcr_far": round(pcr_far, 4),
            "max_oi_call_rel": int(max_oi_call_strike),
            "max_oi_put_rel": int(max_oi_put_strike),
            "oi_concentration": round(oi_concentration, 4),
            "call_oi_gradient": round(call_oi_grad, 2),
            "put_oi_gradient": round(put_oi_grad, 2),
            "iv_skew": round(iv_skew, 4),
            "relative_strike": 0,
        }

    def clear_cache(self):
        """Clear the internal data cache."""
        self._cache.clear()
