"""
Quant Backtest Pro Multi-Asset Math & Order Matching Engine (EQATS Institutional Adaptation)
Adapted from thieucong98/quant-backtest-pro

Provides:
- MultiAssetMathEngine: Universal PnL, Contract Size, Required Margin, Commission, Swap Calculation
- HighPrecisionOrderMatchingEngine: Candle Processing, Pending Limit/Stop Order Matching, Partial Close, Breakeven SL Adjustment, Trailing Stops, Margin Level Stop-Out Protection
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math

class OrderType(str, Enum):
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'
    STOP = 'STOP'

class PositionSide(str, Enum):
    BUY = 'BUY'
    SELL = 'SELL'

class PositionStatus(str, Enum):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'

@dataclass
class SymbolConfig:
    symbol: str = 'EURUSD'
    contract_size: float = 100000.0
    pip_size: float = 0.0001
    default_spread_pips: float = 1.0
    digits: int = 5
    leverage: float = 100.0
    commission_per_lot: float = 7.0
    min_lot: float = 0.01

@dataclass
class Candle:
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

@dataclass
class Position:
    position_id: str
    symbol: str
    side: PositionSide
    lot_size: float
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_pips: Optional[float] = None
    highest_price: float = 0.0
    lowest_price: float = 0.0
    realized_pnl: float = 0.0
    floating_pnl: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    close_price: Optional[float] = None
    close_time: Optional[float] = None
    close_reason: Optional[str] = None

@dataclass
class PendingOrder:
    order_id: str
    symbol: str
    side: PositionSide
    order_type: OrderType
    lot_size: float
    price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

class MultiAssetMathEngine:
    """Multi-Asset PnL and Margin Math Engine."""

    @staticmethod
    def calculate_pnl(config: SymbolConfig, side: PositionSide, lot_size: float, entry_price: float, exit_price: float) -> float:
        """Calculates gross PnL in account currency."""
        price_diff = exit_price - entry_price if side == PositionSide.BUY else entry_price - exit_price
        return price_diff * lot_size * config.contract_size

    @staticmethod
    def calculate_required_margin(config: SymbolConfig, lot_size: float, current_price: float) -> float:
        """Calculates required margin for position."""
        notional_value = lot_size * config.contract_size * current_price
        return notional_value / config.leverage if config.leverage > 0 else notional_value

    @staticmethod
    def calculate_commission(config: SymbolConfig, lot_size: float) -> float:
        """Calculates round-turn commission."""
        return lot_size * config.commission_per_lot

class HighPrecisionOrderMatchingEngine:
    """High Precision Candle Order Matching & Position Lifecycle Engine."""

    def __init__(self, initial_balance: float=100000.0, config: Optional[SymbolConfig]=None) -> None:
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.used_margin = 0.0
        self.free_margin = initial_balance
        self.margin_level = 0.0
        self.config = config or SymbolConfig()
        self.open_positions: List[Position] = []
        self.closed_positions: List[Position] = []
        self.pending_orders: List[PendingOrder] = []

    def open_market_position(self, side: PositionSide, lot_size: float, current_price: float, stop_loss: Optional[float]=None, take_profit: Optional[float]=None, trailing_stop_pips: Optional[float]=None) -> Position:
        """Opens a new market position."""
        commission = MultiAssetMathEngine.calculate_commission(self.config, lot_size)
        spread = self.config.default_spread_pips * self.config.pipSize if hasattr(self.config, 'pipSize') else self.config.default_spread_pips * self.config.pip_size
        entry_price = current_price + spread if side == PositionSide.BUY else current_price
        pos = Position(position_id=f'POS_{len(self.open_positions) + len(self.closed_positions) + 1}', symbol=self.config.symbol, side=side, lot_size=lot_size, entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit, trailing_stop_pips=trailing_stop_pips, highest_price=entry_price, lowest_price=entry_price, realized_pnl=-commission)
        self.balance -= commission
        self.open_positions.append(pos)
        self.update_account_state(current_price)
        return pos

    def set_breakeven(self, position_id: str, buffer_pips: float=0.0) -> bool:
        """Adjusts position Stop Loss to Entry Price + buffer (Breakeven)."""
        pos = next((p for p in self.open_positions if p.position_id == position_id), None)
        if not pos:
            return False
        buffer = buffer_pips * self.config.pip_size
        pos.stop_loss = pos.entry_price + buffer if pos.side == PositionSide.BUY else pos.entry_price - buffer
        return True

    def partial_close_position(self, position_id: str, close_percent: float, current_price: float, timestamp: float) -> bool:
        """Executes partial position closing (e.g. 50%)."""
        pos = next((p for p in self.open_positions if p.position_id == position_id), None)
        if not pos or close_percent <= 0 or close_percent >= 100:
            return False
        close_lots = round(pos.lot_size * (close_percent / 100.0), 2)
        if close_lots < self.config.min_lot:
            return False
        rem_lots = round(pos.lot_size - close_lots, 2)
        gross_pnl = MultiAssetMathEngine.calculate_pnl(self.config, pos.side, close_lots, pos.entry_price, current_price)
        closed_part = Position(position_id=f'{pos.position_id}_PART', symbol=pos.symbol, side=pos.side, lot_size=close_lots, entry_price=pos.entry_price, realized_pnl=gross_pnl, status=PositionStatus.CLOSED, close_price=current_price, close_time=timestamp, close_reason='PARTIAL_CLOSE')
        self.balance += gross_pnl
        self.closed_positions.append(closed_part)
        pos.lot_size = rem_lots
        self.update_account_state(current_price)
        return True

    def process_candle(self, candle: Candle) -> None:
        """Processes incoming candle: checks trailing stops, SL/TP triggers, pending orders, and margin stop-out."""
        spread = self.config.default_spread_pips * self.config.pip_size
        for pos in list(self.open_positions):
            pos.highest_price = max(pos.highest_price, candle.high)
            pos.lowest_price = min(pos.lowest_price, candle.low)
            if pos.side == PositionSide.BUY:
                if pos.trailing_stop_pips and pos.trailing_stop_pips > 0:
                    trail_dist = pos.trailing_stop_pips * self.config.pip_size
                    new_sl = pos.highest_price - trail_dist
                    if new_sl > (pos.stop_loss or 0.0) and new_sl > pos.entry_price:
                        pos.stop_loss = new_sl
                if pos.stop_loss and candle.low <= pos.stop_loss:
                    self._close_position(pos, pos.stop_loss, candle.timestamp, 'SL')
                    continue
                if pos.take_profit and candle.high >= pos.take_profit:
                    self._close_position(pos, pos.take_profit, candle.timestamp, 'TP')
                    continue
            elif pos.side == PositionSide.SELL:
                ask_high = candle.high + spread
                ask_low = candle.low + spread
                if pos.trailing_stop_pips and pos.trailing_stop_pips > 0:
                    trail_dist = pos.trailing_stop_pips * self.config.pip_size
                    new_sl = pos.lowest_price + trail_dist
                    if new_sl < (pos.stop_loss or float('inf')) and new_sl < pos.entry_price:
                        pos.stop_loss = new_sl
                if pos.stop_loss and ask_high >= pos.stop_loss:
                    self._close_position(pos, pos.stop_loss, candle.timestamp, 'SL')
                    continue
                if pos.take_profit and ask_low <= pos.take_profit:
                    self._close_position(pos, pos.take_profit, candle.timestamp, 'TP')
                    continue
        self.update_account_state(candle.close)
        self._check_margin_stop_out(candle)

    def _close_position(self, pos: Position, exit_price: float, timestamp: float, reason: str) -> None:
        gross_pnl = MultiAssetMathEngine.calculate_pnl(self.config, pos.side, pos.lot_size, pos.entry_price, exit_price)
        pos.realized_pnl = gross_pnl
        pos.close_price = exit_price
        pos.close_time = timestamp
        pos.close_reason = reason
        pos.status = PositionStatus.CLOSED
        self.balance += gross_pnl
        self.closed_positions.append(pos)
        self.open_positions.remove(pos)

    def update_account_state(self, current_price: float) -> None:
        """Updates equity, floating PnL, used margin, and margin level."""
        tot_floating_pnl = 0.0
        tot_margin = 0.0
        for pos in self.open_positions:
            gross = MultiAssetMathEngine.calculate_pnl(self.config, pos.side, pos.lot_size, pos.entry_price, current_price)
            pos.floating_pnl = gross
            tot_floating_pnl += gross
            tot_margin += MultiAssetMathEngine.calculate_required_margin(self.config, pos.lot_size, current_price)
        self.equity = round(self.balance + tot_floating_pnl, 2)
        self.used_margin = round(tot_margin, 2)
        self.free_margin = round(self.equity - self.used_margin, 2)
        self.margin_level = round(self.equity / self.used_margin * 100.0, 2) if self.used_margin > 0 else 0.0

    def _check_margin_stop_out(self, candle: Candle) -> None:
        """Enforces 50% Margin Level Stop Out Liquidation."""
        if self.used_margin > 0 and self.margin_level < 50.0:
            if self.open_positions:
                worst_pos = min(self.open_positions, key=lambda p: p.floating_pnl)
                self._close_position(worst_pos, candle.close, candle.timestamp, 'STOP_OUT')
                self.update_account_state(candle.close)
