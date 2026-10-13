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


import logging

import numpy as np
import pandas as pd

# Logging Setup
logger = logging.getLogger("MarketProfile")


class ProfileAnalyzer:
    def __init__(self):
        pass

    def calculate_dalton_value_area(self, df, bins=20, va_pct=0.70):
        """
        Dalton Value Area Algorithm:
        1. Segment price range into 20 horizontal bins
        2. Identify Point of Control (POC)
        3. Expand from POC until 70% Volume is captured
        """
        if df is None or df.empty:
            return None

        try:
            # 1. Segment price range into 20 horizontal bins
            d = df.copy()
            d["bin"] = pd.cut(d["close"], bins=bins)
            v_profile = d.groupby("bin", observed=True)["volume"].sum()

            # 2. Identify Point of Control (POC)
            poc_bin = v_profile.idxmax()
            total_v, va_v = v_profile.sum(), v_profile[poc_bin]

            # 3. Expand from POC until 70% Volume is captured
            # Dalton Rule: Compare up/down bins and pick highest volume in each step
            va_bins = [poc_bin]
            sorted_bins = v_profile.sort_values(ascending=False).index.tolist()
            for b in sorted_bins:
                if va_v >= total_v * va_pct:
                    break
                if b not in va_bins:
                    va_bins.append(b)
                    va_v += v_profile[b]

            # 4. Extract VAH and VAL boundaries
            vah = max([b.right for b in va_bins])
            val = min([b.left for b in va_bins])

            return {
                "poc": float(poc_bin.mid),
                "vah": float(vah),
                "val": float(val),
                "vpoc": float(poc_bin.mid),  # compatibility
                "vvah": float(vah),  # compatibility
                "vval": float(val),  # compatibility
            }
        except Exception as e:
            logger.error(f"Dalton Profile Calc Error: {e}")
            return None

    def calculate_market_profile(self, df, price_step=None, mode="VOLUME"):
        """
        Calculates Market Profile.
        If mode is 'VOLUME' and Phase 65 is enabled, uses Dalton's algorithm.
        """
        from shortcircuit import config

        if getattr(config, "P65_AMT_ENABLED", False) and mode == "VOLUME":
            return self.calculate_dalton_value_area(df)

        if df is None or df.empty:
            return None

        try:
            # 1. Determine Price Bins
            min_p = df["low"].min()
            max_p = df["high"].max()

            if price_step is None:
                price_range = max_p - min_p
                if price_range < 5:
                    price_step = 0.05
                elif price_range < 100:
                    price_step = 0.10
                elif price_range < 1000:
                    price_step = 0.50
                else:
                    price_step = 1.0

            bins = np.arange(min_p, max_p + price_step, price_step)

            # 2. Build Profile
            if mode == "VOLUME":
                # Use np.histogram with weights for Volume Profile
                counts, bin_edges = np.histogram(df["close"], bins=bins, weights=df["volume"])
                label_prefix = "v"  # vPOC, vVAH
            else:
                # Standard TPO (Frequency)
                counts, bin_edges = np.histogram(df["close"], bins=bins)
                label_prefix = ""  # POC, VAH

            # 3. Calculate Value Area (70%)
            total_val = counts.sum()
            if total_val == 0:
                return None
            limit = total_val * 0.70

            # Find POC (Mode)
            poc_idx = np.argmax(counts)
            poc_price = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2

            # Value Area Algorithm: Start at POC and expand adjacently
            current_total = counts[poc_idx]
            up_idx = poc_idx + 1
            dn_idx = poc_idx - 1

            # FIXED: initialize bounds to poc_idx, not to the pre-incremented indices
            low_bound = poc_idx
            high_bound = poc_idx

            while current_total < limit:
                can_go_up = up_idx < len(counts)
                can_go_down = dn_idx >= 0

                if not can_go_up and not can_go_down:
                    break

                up_val = counts[up_idx] if can_go_up else -1
                dn_val = counts[dn_idx] if can_go_down else -1

                if not can_go_down:
                    current_total += up_val
                    high_bound = up_idx
                    up_idx += 1
                elif not can_go_up:
                    current_total += dn_val
                    low_bound = dn_idx
                    dn_idx -= 1
                elif up_val >= dn_val:
                    current_total += up_val
                    high_bound = up_idx
                    up_idx += 1
                else:
                    current_total += dn_val
                    low_bound = dn_idx
                    dn_idx -= 1

            val = bin_edges[max(0, low_bound)]
            vah = bin_edges[min(len(bin_edges) - 1, high_bound + 1)]

            return {
                f"{label_prefix}poc": poc_price,
                f"{label_prefix}vah": vah,
                f"{label_prefix}val": val,
                "poc": poc_price,  # compatibility
                "vah": vah,  # compatibility
                "val": val,  # compatibility
                "counts": counts,
                "bins": bin_edges,
                "total_value": total_val,
                "mode": mode,
            }

        except Exception as e:
            logger.error(f"TPO Calc Error: {e}")
            return None

    def check_profile_rejection(self, df, ltp):
        """
        Signal: "Look Above and Fail"
        Price breaks VAH but closes back inside.
        """
        # We need Context (Profile of the DAY so far)
        # Assuming df contains today's data.

        # Calculate Profile excluding the last few candles (Developing Struct)?
        # No, usually we trade against the Developing Structure of the day.

        profile = self.calculate_market_profile(df, mode="VOLUME")
        if not profile:
            return False, "Profile Error"

        vah = profile["vvah"]
        profile["vpoc"]

        # Logic:
        # Check last 3 candles for the "Probe & Fail" pattern.
        if len(df) < 5:
            return False, "No Data"

        # Setup: One of the recent candles High > VAH
        # Trigger: Current Candle Close < VAH

        recent = df.iloc[-3:]

        # Did we probe above VAH?
        poked_above = recent["high"].max() > vah

        # Are we currently below VAH (and notably below, not just noise)?
        # Buffer: 0.05% below VAH
        curr_close = df.iloc[-1]["close"]
        buffer = vah * 0.9995

        closed_back_in = curr_close < buffer

        # Additional Filter: The 'Fail' should be sharp (Drift logic handles the slow ones)
        # If we poked above, expecting expansion. If we close back in, it's a trap.

        if poked_above and closed_back_in:
            # Confirm it's not just a downtrend staying below VAH.
            # We must have been ABOVE VAH recently.

            # Count closes above VAH in recent history (Acceptance Check)
            # If we accepted above VAH for too long (> 30 mins), VAH might migrate up.
            # But here we assume fixed/developing profile.

            return True, f"Look Above & Fail (VAH: {vah:.2f})"

        return False, f"Inside VA (VAH: {vah:.2f})"
