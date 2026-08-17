"""
Basic Backtesting Framework
Provides backtesting capabilities for trading strategies.
"""

from datetime import datetime as dt
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
import json


@dataclass
class Trade:
    """Represents a single trade in backtest."""
    entry_time: str
    exit_time: Optional[str] = None
    symbol: str = ""
    direction: str = ""  # BUY or SELL
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    lot_size: float = 0.0
    pnl: float = 0.0
    commission: float = 0.0
    sl: Optional[float] = None
    tp: Optional[float] = None
    exit_reason: str = ""


@dataclass
class BacktestResult:
    """Results of a backtest run."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    max_profit: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: dt.now().isoformat())


class BacktestEngine:
    """
    Basic backtesting engine for testing trading strategies.
    """
    
    def __init__(self, initial_balance: float = 10000.0, commission_per_lot: float = 7.0):
        """
        Initialize backtest engine.
        
        Args:
            initial_balance: Starting account balance
            commission_per_lot: Commission per lot traded
        """
        self.initial_balance = initial_balance
        self.commission_per_lot = commission_per_lot
        self.current_balance = initial_balance
        self.positions = {}  # symbol -> position info
        self.trades = []
        self.equity_curve = [initial_balance]
        self.max_equity = initial_balance
        self.max_drawdown = 0.0
        
        # Strategy parameters
        self.strategy_params = {}
    
    def set_strategy_params(self, params: Dict[str, Any]):
        """Set strategy parameters."""
        self.strategy_params = params
    
    def reset(self):
        """Reset backtest state."""
        self.current_balance = self.initial_balance
        self.positions = {}
        self.trades = []
        self.equity_curve = [self.initial_balance]
        self.max_equity = self.initial_balance
        self.max_drawdown = 0.0
    
    def open_position(self, symbol: str, direction: str, lot_size: float, 
                     price: float, sl: float = None, tp: float = None) -> bool:
        """
        Open a position.
        
        Args:
            symbol: Trading symbol
            direction: BUY or SELL
            lot_size: Lot size
            price: Entry price
            sl: Stop loss price
            tp: Take profit price
            
        Returns:
            True if position opened successfully
        """
        if symbol in self.positions:
            return False  # Already have position
        
        commission = self.commission_per_lot * lot_size
        
        self.positions[symbol] = {
            'direction': direction,
            'lot_size': lot_size,
            'entry_price': price,
            'sl': sl,
            'tp': tp,
            'entry_time': dt.now().isoformat(),
            'commission': commission
        }
        
        return True
    
    def close_position(self, symbol: str, exit_price: float, exit_reason: str = "") -> bool:
        """
        Close a position.
        
        Args:
            symbol: Trading symbol
            exit_price: Exit price
            exit_reason: Reason for closing
            
        Returns:
            True if position closed successfully
        """
        if symbol not in self.positions:
            return False
        
        pos = self.positions[symbol]
        
        # Calculate P&L
        if pos['direction'] == 'BUY':
            pnl = (exit_price - pos['entry_price']) * pos['lot_size'] * 100000
        else:  # SELL
            pnl = (pos['entry_price'] - exit_price) * pos['lot_size'] * 100000
        
        pnl -= pos['commission']  # Subtract commission
        
        # Update balance
        self.current_balance += pnl
        
        # Create trade record
        trade = Trade(
            entry_time=pos['entry_time'],
            exit_time=dt.now().isoformat(),
            symbol=symbol,
            direction=pos['direction'],
            entry_price=pos['entry_price'],
            exit_price=exit_price,
            lot_size=pos['lot_size'],
            pnl=pnl,
            commission=pos['commission'],
            sl=pos['sl'],
            tp=pos['tp'],
            exit_reason=exit_reason
        )
        
        self.trades.append(trade)
        
        # Remove position
        del self.positions[symbol]
        
        # Update equity curve
        self._update_equity()
        
        return True
    
    def _update_equity(self):
        """Update equity curve and drawdown."""
        # Calculate unrealized P&L from open positions
        unrealized_pnl = 0.0
        for symbol, pos in self.positions.items():
            # Note: In a real backtest, you'd need current prices
            # For simplicity, we'll assume unrealized P&L is 0 here
            pass
        
        equity = self.current_balance + unrealized_pnl
        self.equity_curve.append(equity)
        
        # Update max equity and drawdown
        if equity > self.max_equity:
            self.max_equity = equity
        
        drawdown = (self.max_equity - equity) / self.max_equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
    
    def run_backtest(self, data: List[Dict[str, Any]], 
                    strategy: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]) -> BacktestResult:
        """
        Run backtest on historical data.
        
        Args:
            data: List of OHLCV data points
            strategy: Strategy function that takes (data_point, strategy_params) and returns trading signals
            
        Returns:
            BacktestResult with performance metrics
        """
        self.reset()
        
        for data_point in data:
            # Get trading signal from strategy
            signal = strategy(data_point, self.strategy_params)
            
            # Process signal
            if signal.get('action') == 'BUY':
                if signal.get('symbol') not in self.positions:
                    self.open_position(
                        symbol=signal.get('symbol', 'EURUSD'),
                        direction='BUY',
                        lot_size=signal.get('lot_size', 0.1),
                        price=data_point.get('close', 0.0),
                        sl=signal.get('sl'),
                        tp=signal.get('tp')
                    )
            
            elif signal.get('action') == 'SELL':
                if signal.get('symbol') not in self.positions:
                    self.open_position(
                        symbol=signal.get('symbol', 'EURUSD'),
                        direction='SELL',
                        lot_size=signal.get('lot_size', 0.1),
                        price=data_point.get('close', 0.0),
                        sl=signal.get('sl'),
                        tp=signal.get('tp')
                    )
            
            elif signal.get('action') == 'CLOSE':
                if signal.get('symbol') in self.positions:
                    self.close_position(
                        symbol=signal.get('symbol'),
                        exit_price=data_point.get('close', 0.0),
                        exit_reason=signal.get('reason', 'Signal')
                    )
            
            # Check stop loss and take profit
            self._check_sl_tp(data_point.get('close', 0.0))
        
        # Close all remaining positions
        for symbol in list(self.positions.keys()):
            self.close_position(symbol, data[-1].get('close', 0.0), 'End of backtest')
        
        # Calculate results
        return self._calculate_results()
    
    def _check_sl_tp(self, current_price: float):
        """Check and execute stop loss and take profit."""
        for symbol, pos in list(self.positions.items()):
            if pos['direction'] == 'BUY':
                if pos['sl'] and current_price <= pos['sl']:
                    self.close_position(symbol, current_price, 'Stop Loss')
                elif pos['tp'] and current_price >= pos['tp']:
                    self.close_position(symbol, current_price, 'Take Profit')
            else:  # SELL
                if pos['sl'] and current_price >= pos['sl']:
                    self.close_position(symbol, current_price, 'Stop Loss')
                elif pos['tp'] and current_price <= pos['tp']:
                    self.close_position(symbol, current_price, 'Take Profit')
    
    def _calculate_results(self) -> BacktestResult:
        """Calculate backtest results."""
        result = BacktestResult()
        
        result.total_trades = len(self.trades)
        result.winning_trades = sum(1 for t in self.trades if t.pnl > 0)
        result.losing_trades = sum(1 for t in self.trades if t.pnl < 0)
        
        if result.total_trades > 0:
            result.win_rate = result.winning_trades / result.total_trades
        
        result.total_pnl = sum(t.pnl for t in self.trades)
        result.max_drawdown = self.max_drawdown
        result.max_profit = max(self.equity_curve) - self.initial_balance
        
        if result.winning_trades > 0:
            result.avg_win = sum(t.pnl for t in self.trades if t.pnl > 0) / result.winning_trades
        
        if result.losing_trades > 0:
            result.avg_loss = sum(t.pnl for t in self.trades if t.pnl < 0) / result.losing_trades
        
        if result.avg_loss != 0:
            result.profit_factor = abs(result.avg_win * result.winning_trades / (result.avg_loss * result.losing_trades))
        
        # Simple Sharpe ratio calculation
        if result.total_pnl > 0 and self.max_drawdown > 0:
            result.sharpe_ratio = result.total_pnl / self.max_drawdown
        
        result.trades = self.trades
        result.equity_curve = self.equity_curve
        
        return result
    
    def save_results(self, result: BacktestResult, filepath: str = "backtest_results.json") -> bool:
        """Save backtest results to file."""
        try:
            data = {
                'total_trades': result.total_trades,
                'winning_trades': result.winning_trades,
                'losing_trades': result.losing_trades,
                'win_rate': result.win_rate,
                'total_pnl': result.total_pnl,
                'max_drawdown': result.max_drawdown,
                'max_profit': result.max_profit,
                'avg_win': result.avg_win,
                'avg_loss': result.avg_loss,
                'profit_factor': result.profit_factor,
                'sharpe_ratio': result.sharpe_ratio,
                'trades': [t.__dict__ for t in result.trades],
                'equity_curve': result.equity_curve,
                'timestamp': result.timestamp
            }
            
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save results: {e}")
            return False


# Simple moving average crossover strategy for testing
def simple_ma_crossover(data_point: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simple moving average crossover strategy.
    
    Args:
        data_point: Current data point with OHLCV
        params: Strategy parameters (fast_ma, slow_ma)
        
    Returns:
        Trading signal
    """
    # This is a placeholder - in a real implementation, you'd calculate MAs
    # from historical data and generate signals based on crossovers
    
    # For testing, return a random signal
    import random
    action = random.choice(['BUY', 'SELL', 'CLOSE', 'HOLD'])
    
    return {
        'action': action,
        'symbol': 'EURUSD',
        'lot_size': 0.1,
        'sl': None,
        'tp': None
    }


# Global backtest engine instance
_backtest_engine = None

def get_backtest_engine(initial_balance: float = 10000.0, commission_per_lot: float = 7.0) -> BacktestEngine:
    """Get the global backtest engine instance."""
    global _backtest_engine
    if _backtest_engine is None:
        _backtest_engine = BacktestEngine(initial_balance, commission_per_lot)
    return _backtest_engine
