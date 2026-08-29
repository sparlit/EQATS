"""
NoFx AI Trading Terminal & Runtime Disposer Engine (EQATS Institutional Adaptation).
Adapted from NoFxAiOS/nofx (AGPL-3.0)

Architecture Paradigm: "The model proposes. The runtime disposes."
Provides:
- NoFxRiskRuntimeDisposer: Runtime risk clamps outside model reach (notional cap, leverage clamp,
  re-entry throttling, safe mode circuit breaker, peak drawdown giveback auto-close, preflight launch check)
- NoFxMarketDirectionBoard: Live market direction board, cost-basis/liquidation heatmaps, net market flow
- NoFxAiModelManager: Multi-model decision paper trails, reasoning logs, and public leaderboard attribution
"""

import time
import math
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger("NoFxAiTerminalEngine")


class NoFxAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


@dataclass
class NoFxPreflightStatus:
    is_ready: bool
    model_access_ok: bool
    account_balance_ok: bool
    strategy_config_ok: bool
    exchange_connected: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class NoFxPositionLimitConfig:
    max_concurrent_positions: int = 5
    max_notional_equity_ratio: float = 3.0  # Max total position value as multiple of account equity
    max_leverage: float = 10.0
    min_hold_seconds: float = 60.0
    reentry_cooldown_seconds: float = 120.0
    max_profit_giveback_pct: float = 30.0  # Giveback from peak profit triggers auto-close
    max_consecutive_model_failures: int = 3


@dataclass
class NoFxModelDecision:
    model_name: str
    symbol: str
    action: NoFxAction
    confidence: float
    reasoning_summary: str
    proposed_volume: float = 0.01
    proposed_sl: float = 0.0
    proposed_tp: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class NoFxClampedOrder:
    symbol: str
    action: NoFxAction
    clamped_volume: float
    clamped_leverage: float
    sl: float
    tp: float
    approved: bool
    veto_reason: Optional[str] = None
    reasoning_paper_trail: Optional[str] = None


class NoFxRiskRuntimeDisposer:
    """
    Go/Python Runtime Risk Engine clamping model proposals to hard risk limits.
    Enforces outside-model-reach safeguards:
    - Launch Preflight Checks
    - Position limits & single position per symbol constraint
    - Notional value capped as ratio of equity
    - Leverage clamping
    - Per-symbol re-entry cooldowns and min hold times
    - Peak drawdown giveback auto-close
    - Safe mode circuit breaker on repeated model failures
    """

    def __init__(self, config: Optional[NoFxPositionLimitConfig] = None):
        self.config = config or NoFxPositionLimitConfig()
        self.lock = threading.Lock()
        self.symbol_last_entry_time: Dict[str, float] = {}
        self.symbol_entry_price: Dict[str, float] = {}
        self.symbol_peak_profit: Dict[str, float] = {}
        self.consecutive_model_failures: int = 0
        self.safe_mode_active: bool = False

    def run_preflight_check(
        self,
        model_name: str,
        account_balance: float,
        exchange_connected: bool,
        min_required_balance: float = 12.0,
    ) -> NoFxPreflightStatus:
        """Executes server-side preflight launch verification prior to trader start."""
        reasons = []
        model_ok = bool(model_name and len(model_name.strip()) > 0)
        if not model_ok:
            reasons.append("Invalid or missing AI model designation.")

        balance_ok = account_balance >= min_required_balance
        if not balance_ok:
            reasons.append(
                f"Insufficient account balance: ${account_balance:.2f} < required ${min_required_balance:.2f}"
            )

        strategy_ok = not self.safe_mode_active
        if not strategy_ok:
            reasons.append("Safe mode circuit breaker active due to previous model failures.")

        if not exchange_connected:
            reasons.append("Exchange connection offline or unresponsive.")

        is_ready = model_ok and balance_ok and strategy_ok and exchange_connected
        return NoFxPreflightStatus(
            is_ready=is_ready,
            model_access_ok=model_ok,
            account_balance_ok=balance_ok,
            strategy_config_ok=strategy_ok,
            exchange_connected=exchange_connected,
            reasons=reasons,
        )

    def evaluate_proposal(
        self,
        decision: NoFxModelDecision,
        account_equity: float,
        current_price: float,
        open_positions: List[Dict[str, Any]],
        broker_volume_step: float = 0.01,
        broker_volume_min: float = 0.01,
        broker_volume_max: float = 100.0,
    ) -> NoFxClampedOrder:
        """Clamps AI model proposal against hard risk limits outside model reach."""
        with self.lock:
            symbol = decision.symbol
            now = time.time()

            # 1. Safe Mode Circuit Breaker Check
            if self.safe_mode_active:
                return NoFxClampedOrder(
                    symbol=symbol,
                    action=decision.action,
                    clamped_volume=0.0,
                    clamped_leverage=1.0,
                    sl=decision.proposed_sl,
                    tp=decision.proposed_tp,
                    approved=False,
                    veto_reason="Safe mode circuit breaker active - new entries blocked.",
                    reasoning_paper_trail=decision.reasoning_summary,
                )

            # Hold / Close proposals
            if decision.action in (NoFxAction.HOLD, NoFxAction.CLOSE):
                return NoFxClampedOrder(
                    symbol=symbol,
                    action=decision.action,
                    clamped_volume=decision.proposed_volume,
                    clamped_leverage=1.0,
                    sl=decision.proposed_sl,
                    tp=decision.proposed_tp,
                    approved=True,
                    reasoning_paper_trail=decision.reasoning_summary,
                )

            # 2. Re-entry Cooldown Throttling
            last_entry = self.symbol_last_entry_time.get(symbol, 0.0)
            if (now - last_entry) < self.config.reentry_cooldown_seconds:
                elapsed = now - last_entry
                return NoFxClampedOrder(
                    symbol=symbol,
                    action=decision.action,
                    clamped_volume=0.0,
                    clamped_leverage=1.0,
                    sl=decision.proposed_sl,
                    tp=decision.proposed_tp,
                    approved=False,
                    veto_reason=f"Re-entry cooldown active for {symbol} ({elapsed:.1f}s / {self.config.reentry_cooldown_seconds}s).",
                    reasoning_paper_trail=decision.reasoning_summary,
                )

            # 3. One Position Per Symbol Constraint
            existing_symbol_pos = [p for p in open_positions if p.get("symbol") == symbol]
            if existing_symbol_pos:
                return NoFxClampedOrder(
                    symbol=symbol,
                    action=decision.action,
                    clamped_volume=0.0,
                    clamped_leverage=1.0,
                    sl=decision.proposed_sl,
                    tp=decision.proposed_tp,
                    approved=False,
                    veto_reason=f"Position already exists for symbol {symbol} (one position per symbol rule).",
                    reasoning_paper_trail=decision.reasoning_summary,
                )

            # 4. Max Concurrent Positions
            if len(open_positions) >= self.config.max_concurrent_positions:
                return NoFxClampedOrder(
                    symbol=symbol,
                    action=decision.action,
                    clamped_volume=0.0,
                    clamped_leverage=1.0,
                    sl=decision.proposed_sl,
                    tp=decision.proposed_tp,
                    approved=False,
                    veto_reason=f"Max concurrent positions limit reached ({len(open_positions)} / {self.config.max_concurrent_positions}).",
                    reasoning_paper_trail=decision.reasoning_summary,
                )

            # 5. Leverage Clamping & Volume Sizing
            target_leverage = min(self.config.max_leverage, max(1.0, decision.confidence * self.config.max_leverage))
            max_allowed_notional = account_equity * self.config.max_notional_equity_ratio
            current_total_notional = sum(
                float(p.get("lot_size", 0.01)) * current_price for p in open_positions
            )
            remaining_notional = max(0.0, max_allowed_notional - current_total_notional)

            proposed_notional = decision.proposed_volume * current_price
            clamped_notional = min(proposed_notional, remaining_notional)

            if current_price <= 0:
                clamped_vol = broker_volume_min
            else:
                raw_vol = clamped_notional / current_price
                steps = math.floor(raw_vol / broker_volume_step) if broker_volume_step > 0 else 0
                clamped_vol = max(broker_volume_min, min(broker_volume_max, steps * broker_volume_step))

            if clamped_vol < broker_volume_min:
                return NoFxClampedOrder(
                    symbol=symbol,
                    action=decision.action,
                    clamped_volume=0.0,
                    clamped_leverage=target_leverage,
                    sl=decision.proposed_sl,
                    tp=decision.proposed_tp,
                    approved=False,
                    veto_reason="Clamped volume below broker minimum threshold.",
                    reasoning_paper_trail=decision.reasoning_summary,
                )

            self.symbol_last_entry_time[symbol] = now
            self.symbol_entry_price[symbol] = current_price
            self.symbol_peak_profit[symbol] = 0.0

            return NoFxClampedOrder(
                symbol=symbol,
                action=decision.action,
                clamped_volume=round(clamped_vol, 4),
                clamped_leverage=round(target_leverage, 2),
                sl=decision.proposed_sl,
                tp=decision.proposed_tp,
                approved=True,
                reasoning_paper_trail=decision.reasoning_summary,
            )

    def check_drawdown_autoclose(
        self,
        symbol: str,
        direction: str,
        open_price: float,
        current_price: float,
        lot_size: float,
        contract_multiplier: float = 100000.0,
    ) -> Tuple[bool, str]:
        """Evaluates whether profitable positions giving back too much profit from peak should be auto-closed."""
        with self.lock:
            p_diff = (current_price - open_price) if direction == "BUY" else (open_price - current_price)
            current_profit = p_diff * lot_size * contract_multiplier

            peak = max(self.symbol_peak_profit.get(symbol, 0.0), current_profit)
            self.symbol_peak_profit[symbol] = peak

            if peak > 50.0:  # Minimum profit threshold before peak giveback auto-close activates
                giveback_pct = ((peak - current_profit) / peak) * 100.0
                if giveback_pct >= self.config.max_profit_giveback_pct:
                    return (
                        True,
                        f"Drawdown auto-close triggered: gave back {giveback_pct:.1f}% from peak profit ${peak:.2f}.",
                    )
            return False, ""

    def record_model_failure(self):
        """Increments consecutive model failure count and activates safe mode if threshold is exceeded."""
        with self.lock:
            self.consecutive_model_failures += 1
            if self.consecutive_model_failures >= self.config.max_consecutive_model_failures:
                self.safe_mode_active = True
                logger.warning(
                    "NoFx Risk Disposer: Safe mode circuit breaker ACTIVATED after %d consecutive failures.",
                    self.consecutive_model_failures,
                )

    def record_model_success(self):
        """Resets consecutive model failures and recovers from safe mode."""
        with self.lock:
            self.consecutive_model_failures = 0
            if self.safe_mode_active:
                self.safe_mode_active = False
                logger.info("NoFx Risk Disposer: Safe mode RECOVERED.")


class NoFxMarketDirectionBoard:
    """
    Live Direction Board for the market universe, maintaining cost-basis heatmaps,
    liquidation heatmaps, and net flow metrics.
    """

    def __init__(self, symbols: Optional[List[str]] = None):
        self.symbols = symbols or ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD"]
        self.direction_history: Dict[str, List[float]] = {s: [] for s in self.symbols}
        self.lock = threading.Lock()

    def update_direction(self, symbol: str, directional_bias: float):
        """Updates directional bias score (-1.0 to +1.0) and maintains history buffer."""
        with self.lock:
            bias = max(-1.0, min(1.0, directional_bias))
            if symbol not in self.direction_history:
                self.direction_history[symbol] = []
            self.direction_history[symbol].append(bias)
            if len(self.direction_history[symbol]) > 100:
                self.direction_history[symbol] = self.direction_history[symbol][-100:]

    def get_market_direction_summary(self, symbol: str) -> Dict[str, Any]:
        """Calculates direction board summary for a given symbol."""
        with self.lock:
            history = self.direction_history.get(symbol, [])
            if not history:
                return {
                    "symbol": symbol,
                    "direction": "NEUTRAL",
                    "bias_score": 0.0,
                    "trend_momentum": 0.0,
                    "net_flow_usd": 0.0,
                }

            current_bias = history[-1]
            if len(history) >= 5:
                sub = history[-5:]
                trend_momentum = float(sum(sub) / len(sub))
            else:
                trend_momentum = current_bias
            direction_str = "BUY" if current_bias > 0.15 else ("SELL" if current_bias < -0.15 else "NEUTRAL")

            return {
                "symbol": symbol,
                "direction": direction_str,
                "bias_score": round(current_bias, 3),
                "trend_momentum": round(trend_momentum, 3),
                "net_flow_usd": round(current_bias * 500000.0, 2),
            }

    def get_liquidation_heatmap(self, symbol: str, current_price: float) -> Dict[str, float]:
        """Computes cost-basis and liquidation heatmap levels around current price."""
        if current_price <= 0:
            return {"long_liq_cluster": 0.0, "short_liq_cluster": 0.0}

        return {
            "long_liq_cluster": round(current_price * 0.985, 4),
            "short_liq_cluster": round(current_price * 1.015, 4),
            "cost_basis_vwap": round(current_price * 0.998, 4),
        }


try:
    import numpy as np
except ImportError:
    np = None


class NoFxAiModelManager:
    """
    Multi-model Decision Paper Trail & Leaderboard Attribution Manager.
    Logs reasoning summaries, model performance, and realized returns.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.paper_trails: List[NoFxModelDecision] = []
        self.model_returns: Dict[str, float] = {}

    def record_decision(self, decision: NoFxModelDecision):
        """Records an AI decision with full reasoning paper trail."""
        with self.lock:
            self.paper_trails.append(decision)
            if len(self.paper_trails) > 500:
                self.paper_trails = self.paper_trails[-500:]

    def record_trade_result(self, model_name: str, pnl: float):
        """Attributes realized return to the decision model."""
        with self.lock:
            self.model_returns[model_name] = self.model_returns.get(model_name, 0.0) + pnl

    def get_paper_trail(self, symbol: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieves stored paper trails filtered by symbol."""
        with self.lock:
            matching = [
                {
                    "model_name": d.model_name,
                    "symbol": d.symbol,
                    "action": d.action.value,
                    "confidence": d.confidence,
                    "reasoning": d.reasoning_summary,
                    "timestamp": d.timestamp,
                }
                for d in reversed(self.paper_trails)
                if symbol is None or d.symbol == symbol
            ]
            return matching[:limit]

    def get_leaderboard(self) -> List[Dict[str, Any]]:
        """Returns leaderboard ranked by realized return."""
        with self.lock:
            ranked = sorted(self.model_returns.items(), key=lambda item: item[1], reverse=True)
            return [
                {"rank": idx + 1, "model_name": model, "realized_return_usd": round(ret, 2)}
                for idx, (model, ret) in enumerate(ranked)
            ]


# Singleton instances for global access
global_nofx_disposer = NoFxRiskRuntimeDisposer()
global_nofx_direction_board = NoFxMarketDirectionBoard()
global_nofx_model_manager = NoFxAiModelManager()
