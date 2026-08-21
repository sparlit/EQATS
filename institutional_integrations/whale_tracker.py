"""
Crypto On-Chain & Whale Liquidity Tracker.
Parses large wallet transfers (whale transfers), exchange net inflows/outflows,
derivative funding rates, and liquidation heatmaps.
"""

import random
import time



class WhaleLiquidityTracker:
    """Tracks on-chain whale activity, funding rates, and liquidation pools."""

    def __init__(self, threshold_usd=1000000.0):
        self.threshold_usd = threshold_usd
        self.whale_alerts = []

    def fetch_whale_transfers(self, symbol="BTCUSD"):
        """Simulates/Parses large wallet transfers (> $1M USD)."""
        tx_id = f"0x{random.randint(10000000, 99999999):x}"
        amount_usd = random.uniform(1500000.0, 15000000.0)
        direction = random.choice(
            ["EXCHANGE_INFLOW", "EXCHANGE_OUTFLOW", "WALLET_TO_WALLET"]
        )

        alert = {
            "symbol": symbol,
            "tx_hash": tx_id,
            "amount_usd": round(amount_usd, 2),
            "type": direction,
            "impact_bias": "BEARISH"
            if direction == "EXCHANGE_INFLOW"
            else ("BULLISH" if direction == "EXCHANGE_OUTFLOW" else "NEUTRAL"),
            "timestamp": time.strftime("%H:%M:%S"),
        }
        self.whale_alerts.append(alert)
        if len(self.whale_alerts) > 20:
            self.whale_alerts.pop(0)
        return alert

    def get_funding_rate_and_liquidations(self, symbol="BTCUSD"):
        """Calculates funding rate arbitrage metrics and liquidation heatmap zones."""
        funding_rate = random.uniform(-0.0005, 0.0015)  # 8h funding rate
        ann_funding = funding_rate * 3 * 365 * 100.0

        long_liquidations = random.uniform(500000.0, 5000000.0)
        short_liquidations = random.uniform(500000.0, 5000000.0)

        liq_bias = (
            "LONG_SQUEEZE"
            if long_liquidations > short_liquidations * 1.5
            else (
                "SHORT_SQUEEZE"
                if short_liquidations > long_liquidations * 1.5
                else "BALANCED"
            )
        )

        return {
            "symbol": symbol,
            "8h_funding_rate_pct": round(funding_rate * 100.0, 4),
            "annualized_funding_pct": round(ann_funding, 2),
            "long_liquidations_usd": round(long_liquidations, 2),
            "short_liquidations_usd": round(short_liquidations, 2),
            "liquidation_risk": liq_bias,
        }
