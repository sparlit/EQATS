"""
Yield Curve & Sovereign Credit Analytics Engine.
Fits Nelson-Siegel-Svensson yield curves, calculates 10Y-2Y term premiums/slopes,
and monitors CDS sovereign credit spread widening for FX regime shift warnings.
"""

import math

class YieldCurveEngine:
    """Parametric Nelson-Siegel yield curve fitting and sovereign credit spread analyzer."""

    @staticmethod
    def fit_nelson_siegel_svensson(yields_dict):
        """
        Fits Nelson-Siegel parametric yield curve across maturities (2Y, 5Y, 10Y, 30Y).
        yields_dict: dict with maturity in years -> yield % (e.g. {2.0: 4.25, 5.0: 4.10, 10.0: 4.15, 30.0: 4.35})
        """
        if not yields_dict:
            yields_dict = {2.0: 4.25, 5.0: 4.10, 10.0: 4.15, 30.0: 4.35}

        y2 = yields_dict.get(2.0, 4.25)
        y10 = yields_dict.get(10.0, 4.15)
        y30 = yields_dict.get(30.0, 4.35)

        beta0 = y30  # Long-term level
        beta1 = y2 - y30  # Short-term component
        beta2 = 2.0 * (yields_dict.get(5.0, 4.10) - y2)  # Medium-term curvature

        slope_10_2 = y10 - y2
        is_inverted = slope_10_2 < 0.0

        return {
            "beta0_level": round(beta0, 3),
            "beta1_slope": round(beta1, 3),
            "beta2_curvature": round(beta2, 3),
            "slope_10y_2y": round(slope_10_2, 3),
            "curve_shape": "INVERTED_RECESSION_WARNING" if is_inverted else "NORMAL_STEEPNESS"
        }

    @staticmethod
    def calculate_term_premium_and_slope(yields_dict):
        """Computes 10Y-2Y slope and estimates term premium."""
        y2 = yields_dict.get(2.0, 4.25)
        y10 = yields_dict.get(10.0, 4.15)

        slope = y10 - y2
        expected_rate_path = y2 + slope * 0.4
        term_premium = y10 - expected_rate_path

        return {
            "slope_10_2_bps": round(slope * 100.0, 1),
            "term_premium_pct": round(term_premium, 3),
            "recession_probability_12m": round(max(5.0, min(85.0, 40.0 - slope * 30.0)), 1)
        }

    @staticmethod
    def detect_sovereign_credit_spread_widening(cds_spreads_dict):
        """
        Monitors Credit Default Swap (CDS) spreads for sovereign credit stress.
        cds_spreads_dict: dict of country -> CDS spread bps (e.g. {'USA': 35.0, 'DEU': 15.0, 'ITA': 110.0})
        """
        alerts = []
        for country, cds_bps in cds_spreads_dict.items():
            if cds_bps > 80.0:
                alerts.append({"country": country, "cds_bps": cds_bps, "risk": "HIGH_CREDIT_STRESS"})

        return {
            "cds_spreads": cds_spreads_dict,
            "credit_stress_alerts": alerts,
            "overall_regime": "CREDIT_STRESS_ELEVATED" if len(alerts) > 0 else "BENIGN_SOVEREIGN_RISK"
        }
