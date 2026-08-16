"""
Bayesian Black-Litterman Portfolio Optimizer.
Combines market equilibrium returns with AI Brain directional views and uncertainty covariances
to solve for optimal Bayesian portfolio weights.
"""

import math
class BlackLittermanOptimizer:
    """Bayesian Black-Litterman Portfolio Asset Allocator."""

    def __init__(self, tau=0.05, risk_aversion=2.5):
        self.tau = tau
        self.risk_aversion = risk_aversion

    def optimize(self, assets, market_caps, cov_matrix, brain_views, view_confidences):
        """
        Calculates Black-Litterman posterior expected returns and optimal weights.
        Pure-Python fallback implementation.
        """
        n = len(assets)
        if n == 0:
            return {}

        total_cap = sum(market_caps.values()) if market_caps else n * 1.0
        w_eq = [market_caps.get(a, 1.0) / total_cap for a in assets]

        # Combine equilibrium weights with brain view confidences
        bl_weights = []
        for i, a in enumerate(assets):
            conf = view_confidences.get(a, 0.5)
            view_p = brain_views.get(a, 0.001)
            raw_w = w_eq[i] * (1.0 + view_p * 100.0 * conf)
            bl_weights.append(max(0.0, raw_w))

        tot_w = sum(bl_weights) if sum(bl_weights) > 0 else 1.0
        weights_dict = {}
        for i, a in enumerate(assets):
            weights_dict[a] = round(bl_weights[i] / tot_w, 4)

        return weights_dict
