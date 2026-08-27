"""
Black Swan Historical Stress Testing & Monte Carlo Risk Engine.
Evaluates portfolio survival, drawdown limits, and margin buffers across historical crises:
- 2008 Lehman Brothers Liquidity Crisis (-25% Daily Shock)
- 2015 SNB Swiss Franc Unpeg Flash Crash (-30% FX Shock)
- 2020 COVID-19 Liquidity Shock (-15% Global Risk-Off Shock)
- 2023 SVB Bank Run Crisis (-10% Credit / Crypto Squeeze)
"""



class BlackSwanStressEngine:
    """Simulates severe tail risk scenarios and stress tests portfolio equity."""

    HISTORICAL_SCENARIOS = {
        "2008_LEHMAN_COLLAPSE": {
            "asset_shock_pct": -0.25,
            "volatility_mult": 4.0,
            "description": "Global Interbank Liquidity Collapse",
        },
        "2015_SNB_CHF_FLASH_CRASH": {
            "asset_shock_pct": -0.30,
            "volatility_mult": 6.0,
            "description": "Swiss Franc Currency Unpeg Shock",
        },
        "2020_COVID_LIQUIDITY_SHOCK": {
            "asset_shock_pct": -0.15,
            "volatility_mult": 3.0,
            "description": "Global Pandemic Liquidity Squeeze",
        },
        "2023_SVB_BANK_RUN": {
            "asset_shock_pct": -0.10,
            "volatility_mult": 2.5,
            "description": "Regional Banking & USDC Depeg Squeeze",
        },
    }

    @classmethod
    def run_stress_test(cls, initial_equity=10000.0, open_positions_count=3):
        """Simulates all historical Black Swan scenarios on the active account equity."""
        results = {}
        for scenario_id, config in cls.HISTORICAL_SCENARIOS.items():
            shock = config["asset_shock_pct"]

            # Position loss under extreme gapping/slippage
            position_drag = open_positions_count * 0.05  # 5% leverage amplification
            total_impact_pct = shock * (1.0 + position_drag)
            stressed_equity = initial_equity * (1.0 + total_impact_pct)
            drawdown_usd = initial_equity - stressed_equity

            margin_call_triggered = stressed_equity < (
                initial_equity * 0.20
            )  # 20% margin level

            results[scenario_id] = {
                "description": config["description"],
                "shock_pct": round(shock * 100.0, 1),
                "stressed_equity": round(stressed_equity, 2),
                "drawdown_usd": round(drawdown_usd, 2),
                "drawdown_pct": round(abs(total_impact_pct) * 100.0, 2),
                "margin_call_risk": margin_call_triggered,
                "status": "PASS (SURVIVED)"
                if not margin_call_triggered
                else "FAIL (MARGIN CALL)",
            }
        return results
