"""
FTMO V5 Risk Control & Qualification Auditor Engine.
Enforces FTMO CE(S)T daily loss limits, maximum total loss limits, news window embargoes,
weekend/closure prohibitions, trade frequency caps, and Best Day Rule qualification metrics.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence


class FTMORiskGuardEngine:
    """
    FTMO Risk Guard Engine.
    Evaluates order execution requests against strict FTMO challenge and funded account rules.
    """

    def __init__(
        self,
        initial_balance: float = 100000.0,
        max_daily_loss_pct: float = 5.0,
        max_total_loss_pct: float = 10.0,
        inner_daily_stop_pct: float = 4.5,
        inner_total_stop_pct: float = 9.0,
    ):
        self.initial_balance = initial_balance
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_total_loss_pct = max_total_loss_pct
        self.inner_daily_stop_pct = inner_daily_stop_pct
        self.inner_total_stop_pct = inner_total_stop_pct

    def evaluate_order_risk(self, symbol: str, action: str, volume: float, price: float, sl: float, current_equity: float, day_start_equity: float, is_news_window: bool=False, is_weekend_embargo: bool=False) -> Dict[str, Any]:
        act_upper = action.upper()
        if act_upper in ['CLOSE', 'CANCEL']:
            return {'decision': 'ALLOW', 'reason': 'Risk reduction request approved'}
        if is_weekend_embargo:
            return {'decision': 'REJECT', 'reason': 'Weekend / market closure embargo active (no new risk)'}
        if is_news_window:
            return {'decision': 'REJECT', 'reason': 'High-impact news embargo window active'}
        daily_loss = day_start_equity - current_equity
        max_daily_allowed = day_start_equity * (self.inner_daily_stop_pct / 100.0)
        if daily_loss >= max_daily_allowed:
            return {
                "decision": "REJECT",
                "reason": f"Daily loss {daily_loss:.2f} reached inner stop threshold ({self.inner_daily_stop_pct}%)",
            }

        # Total Loss Check against inner stop
        total_loss = self.initial_balance - current_equity
        max_total_allowed = self.initial_balance * (self.inner_total_stop_pct / 100.0)
        if total_loss >= max_total_allowed:
            return {
                "decision": "REJECT",
                "reason": f"Total loss {total_loss:.2f} reached inner stop threshold ({self.inner_total_stop_pct}%)",
            }

        # Calculate proposed order risk
        pip_size = 0.01 if "JPY" in symbol.upper() else 0.0001
        sl_dist = abs(price - sl) if sl > 0 else (pip_size * 30.0)
        order_risk = volume * 100000.0 * sl_dist
        if daily_loss + order_risk > max_daily_allowed:
            return {'decision': 'REJECT', 'reason': f'Proposed order risk {order_risk:.2f} exceeds remaining daily buffer'}
        return {'decision': 'ALLOW', 'reason': 'FTMO pre-trade risk checks passed', 'order_risk': round(order_risk, 2)}

        if (daily_loss + order_risk) > max_daily_allowed:
            return {
                "decision": "REJECT",
                "reason": f"Proposed order risk {order_risk:.2f} exceeds remaining daily buffer",
            }

        return {"decision": "ALLOW", "reason": "FTMO pre-trade risk checks passed", "order_risk": round(order_risk, 2)}


class FTMOQualificationAuditor:
    """
    Calculates FTMO Challenge Qualification, Minimum Trading Days, and Best Day Rule metrics.
    """

    def evaluate_qualification(
        self,
        starting_balance: float,
        current_equity: float,
        target_profit_pct: float,
        closed_trades: List[Dict[str, Any]],
        min_trading_days: int = 4,
        best_day_rule_pct: Optional[float] = 0.50,
    ) -> Dict[str, Any]:
        target_amount = starting_balance * (target_profit_pct / 100.0)
        current_profit = current_equity - starting_balance

        # Group profit per day
        daily_pnl: Dict[str, float] = {}
        for trade in closed_trades:
            day_key = str(trade.get('ftmo_day', 'DAY1'))
            daily_pnl[day_key] = daily_pnl.get(day_key, 0.0) + float(trade.get('net_profit', 0.0))
        trading_days = len(daily_pnl)
        positive_days_profit = sum((p for p in daily_pnl.values() if p > 0))
        best_day_profit = max([p for p in daily_pnl.values() if p > 0] + [0.0])
        best_day_ratio = best_day_profit / positive_days_profit if positive_days_profit > 0 else 0.0
        best_day_compliant = True
        if best_day_rule_pct is not None and positive_days_profit > 0:
            best_day_compliant = best_day_ratio <= best_day_rule_pct
        profit_target_met = current_profit >= target_amount
        min_days_met = trading_days >= min_trading_days
        fully_qualified = profit_target_met and min_days_met and best_day_compliant

        return {
            "starting_balance": starting_balance,
            "current_equity": current_equity,
            "current_profit": round(current_profit, 2),
            "target_amount": round(target_amount, 2),
            "profit_target_met": profit_target_met,
            "trading_days": trading_days,
            "min_trading_days": min_trading_days,
            "min_days_met": min_days_met,
            "best_day_profit": round(best_day_profit, 2),
            "best_day_ratio": round(best_day_ratio, 4),
            "best_day_compliant": best_day_compliant,
            "fully_qualified": fully_qualified,
        }
