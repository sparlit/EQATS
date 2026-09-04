"""
Volatility Surface Model
────────────────────────
Uses IV skew and term structure to select optimal strikes instead of
always picking ATM. Considers:

  1. IV Smile/Skew — find strikes with cheapest relative IV
  2. Moneyness sweet spot — slight OTM for better risk/reward
  3. Liquidity filter — avoid illiquid strikes (low OI)
  4. Risk-profile aware — LOW stays near ATM, HIGH goes further OTM

Usage:
  from strategy.vol_surface import VolSurfaceModel
  model = VolSurfaceModel(max_strike_offset=2)
  strike, score = model.select_optimal_strike(
      spot=23500, direction="CALL", expiry=date(2026,3,17),
      option_data=df, risk_profile=profile)
"""

import math
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from features.option_chain_features import (
    parse_option_symbol, compute_atm_strike, estimate_iv_from_premium,
    STRIKE_GAP,
)
from utils.logger import get_logger

logger = get_logger("vol_surface")


class VolSurfaceModel:
    """Selects optimal option strike using IV surface analysis."""

    def __init__(self, max_strike_offset: int = 2):
        self.max_strike_offset = max_strike_offset

    def build_iv_surface(
        self,
        option_data: pd.DataFrame,
        spot: float,
        expiry: date,
        ref_date: date,
    ) -> pd.DataFrame:
        """
        Build IV surface from option premium data.

        option_data must have columns: symbol, close, oi, volume
        Returns DataFrame with: strike, option_type, premium, oi, volume, iv,
                                 relative_strike, moneyness
        """
        if option_data.empty:
            return pd.DataFrame()

        dte = max((expiry - ref_date).days, 1)
        atm = compute_atm_strike(spot)
        rows = []

        for _, row in option_data.iterrows():
            parsed = parse_option_symbol(row["symbol"])
            if parsed is None:
                continue
            if parsed["expiry_date"] != expiry:
                continue

            strike = parsed["strike"]
            opt_type = parsed["option_type"]
            premium = row.get("close", 0)
            oi = row.get("oi", 0)
            volume = row.get("volume", 0)

            if premium <= 0:
                continue

            iv = estimate_iv_from_premium(
                premium, spot, strike, dte, opt_type
            )

            rel_strike = int((strike - atm) / STRIKE_GAP)
            # Moneyness: 0 = ATM, positive = OTM for calls, ITM for puts
            if opt_type == "CE":
                moneyness = (strike - spot) / spot
            else:
                moneyness = (spot - strike) / spot

            rows.append({
                "strike": strike,
                "option_type": opt_type,
                "premium": premium,
                "oi": oi,
                "volume": volume,
                "iv": iv,
                "relative_strike": rel_strike,
                "moneyness": moneyness,
                "dte": dte,
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return df

    def _score_strike(
        self,
        row: dict,
        direction: str,
        iv_surface: pd.DataFrame,
        spot: float,
    ) -> float:
        """
        Score a candidate strike (higher = better).

        Factors:
          1. IV edge: prefer lower IV vs same-type average (cheaper option)
          2. Moneyness sweet spot: slight OTM (0.5-1.5% for calls) is optimal
          3. Liquidity: prefer higher OI
          4. Premium efficiency: lower premium = higher leverage
          5. Theta decay: avoid very low DTE + deep OTM (fast decay)
        """
        score = 0.0

        opt_type = "CE" if direction == "CALL" else "PE"
        same_type = iv_surface[iv_surface["option_type"] == opt_type]
        if same_type.empty:
            return 0.0

        # 1. IV Edge (30% weight) — lower IV relative to average = cheaper
        avg_iv = same_type["iv"].mean()
        if avg_iv > 0 and row["iv"] > 0:
            iv_edge = (avg_iv - row["iv"]) / avg_iv
            score += 0.30 * np.clip(iv_edge, -0.5, 0.5)

        # 2. Moneyness sweet spot (25% weight)
        # For CALLs: slight OTM (0.3-1.5% above spot) is optimal
        # For PUTs: slight OTM (0.3-1.5% below spot) is optimal
        moneyness = row["moneyness"]
        if 0.002 <= moneyness <= 0.015:
            # Sweet spot: slight OTM
            score += 0.25
        elif -0.005 <= moneyness < 0.002:
            # Near ATM: good but not optimal
            score += 0.20
        elif 0.015 < moneyness <= 0.030:
            # Moderate OTM: decent leverage but more risk
            score += 0.15
        else:
            # Deep ITM or very far OTM
            score += 0.05

        # 3. Liquidity (20% weight) — normalized OI
        max_oi = same_type["oi"].max()
        if max_oi > 0:
            oi_ratio = row["oi"] / max_oi
            score += 0.20 * oi_ratio

        # 4. Premium efficiency (15% weight) — lower premium = more leverage
        max_prem = same_type["premium"].max()
        if max_prem > 0:
            prem_eff = 1.0 - (row["premium"] / max_prem)
            score += 0.15 * np.clip(prem_eff, 0, 1)

        # 5. Theta penalty (10% weight) — penalize far OTM with low DTE
        dte = row.get("dte", 5)
        if dte <= 1 and abs(row["relative_strike"]) > 2:
            score -= 0.10  # heavy theta decay risk
        elif dte <= 2 and abs(row["relative_strike"]) > 3:
            score -= 0.05

        return round(score, 4)

    def select_optimal_strike(
        self,
        spot: float,
        direction: str,
        expiry: date,
        ref_date: date,
        option_data: pd.DataFrame,
        regime: str = "UNKNOWN",
    ) -> Optional[Dict]:
        """
        Select the optimal strike for a trade.

        Returns dict with: strike, iv, premium, score, relative_strike
        or None if no suitable strike found.
        """
        iv_surface = self.build_iv_surface(option_data, spot, expiry, ref_date)
        if iv_surface.empty:
            return None

        opt_type = "CE" if direction == "CALL" else "PE"
        candidates = iv_surface[iv_surface["option_type"] == opt_type].copy()

        if candidates.empty:
            return None

        atm = compute_atm_strike(spot)

        # Filter to allowed strike range
        candidates = candidates[
            candidates["relative_strike"].abs() <= self.max_strike_offset
        ]

        if candidates.empty:
            # Fall back to closest available
            candidates = iv_surface[iv_surface["option_type"] == opt_type].copy()
            if candidates.empty:
                return None
            # Take closest to ATM
            candidates["dist"] = (candidates["strike"] - atm).abs()
            candidates = candidates.nsmallest(3, "dist")

        # Score each candidate
        candidates["score"] = candidates.apply(
            lambda r: self._score_strike(r.to_dict(), direction, iv_surface, spot),
            axis=1,
        )

        # Pick highest score
        best = candidates.loc[candidates["score"].idxmax()]

        return {
            "strike": int(best["strike"]),
            "iv": round(best["iv"], 4),
            "premium": round(best["premium"], 2),
            "score": round(best["score"], 4),
            "relative_strike": int(best["relative_strike"]),
            "moneyness": round(best["moneyness"], 4),
            "oi": int(best["oi"]),
        }

    def get_iv_skew_summary(
        self,
        iv_surface: pd.DataFrame,
    ) -> Dict:
        """
        Summarize the IV skew for signal enrichment.
        
        Returns: call_iv_avg, put_iv_avg, skew (put-call), smile_curvature
        """
        if iv_surface.empty:
            return {"call_iv": 0, "put_iv": 0, "skew": 0, "smile": 0}

        calls = iv_surface[iv_surface["option_type"] == "CE"]
        puts = iv_surface[iv_surface["option_type"] == "PE"]

        call_iv = calls["iv"].mean() if not calls.empty else 0
        put_iv = puts["iv"].mean() if not puts.empty else 0
        skew = put_iv - call_iv

        # Smile curvature: IV at wings vs ATM
        atm = iv_surface[iv_surface["relative_strike"].abs() <= 1]
        wings = iv_surface[iv_surface["relative_strike"].abs() >= 2]
        atm_iv = atm["iv"].mean() if not atm.empty else 0
        wing_iv = wings["iv"].mean() if not wings.empty else 0
        smile = wing_iv - atm_iv if atm_iv > 0 else 0

        return {
            "call_iv": round(call_iv, 4),
            "put_iv": round(put_iv, 4),
            "skew": round(skew, 4),
            "smile": round(smile, 4),
        }
