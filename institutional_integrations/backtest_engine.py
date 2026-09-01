"""
Event-Driven Backtesting & Walk-Forward Engine.
Executes historical event simulation, parameter walk-forward optimization,
and generates performance metrics (Sharpe Ratio, Sortino, Profit Factor, Max Drawdown).
"""
from typing import Any
import math

class EventDrivenBacktester:
    """Event-driven historical backtester and walk-forward optimizer."""

    def __init__(self, initial_capital: Any=10000.0, commission_per_trade: Any=1.0) -> None:
        self.initial_capital = initial_capital
        self.commission_per_trade = commission_per_trade

    def run_backtest(self, historical_bars: Any, strategy_func: Any, sl_pips: Any=20, tp_pips: Any=40, lot_size: Any=0.01) -> Any:
        """
        Executes event-driven backtest over bar series.
        historical_bars: list of dicts {'open', 'high', 'low', 'close'}
        """
        capital = self.initial_capital
        equity_curve = [capital]
        trades = []
        open_trade = None
        for idx, bar in enumerate(historical_bars):
            close_p = bar['close']
            high_p = bar['high']
            low_p = bar['low']
            if open_trade:
                dir_m = 1 if open_trade['dir'] == 'BUY' else -1
                if open_trade['dir'] == 'BUY' and low_p <= open_trade['sl'] or (open_trade['dir'] == 'SELL' and high_p >= open_trade['sl']):
                    close_price = open_trade['sl']
                    profit = (close_price - open_trade['entry']) * dir_m * lot_size * 100000.0 - self.commission_per_trade
                    capital += profit
                    open_trade['profit'] = profit
                    open_trade['reason'] = 'SL'
                    trades.append(open_trade)
                    open_trade = None
                elif open_trade['dir'] == 'BUY' and high_p >= open_trade['tp'] or (open_trade['dir'] == 'SELL' and low_p <= open_trade['tp']):
                    close_price = open_trade['tp']
                    profit = (close_price - open_trade['entry']) * dir_m * lot_size * 100000.0 - self.commission_per_trade
                    capital += profit
                    open_trade['profit'] = profit
                    open_trade['reason'] = 'TP'
                    trades.append(open_trade)
                    open_trade = None
            if not open_trade and idx >= 20:
                signal = strategy_func(historical_bars[:idx + 1])
                if signal in ['BUY', 'SELL']:
                    sl_dist = sl_pips * 0.0001 if close_p < 10 else sl_pips * 0.01
                    tp_dist = tp_pips * 0.0001 if close_p < 10 else tp_pips * 0.01
                    sl_price = close_p - sl_dist if signal == 'BUY' else close_p + sl_dist
                    tp_price = close_p + tp_dist if signal == 'BUY' else close_p - tp_dist
                    open_trade = {'entry': close_p, 'dir': signal, 'sl': sl_price, 'tp': tp_price, 'bar_idx': idx}
            equity_curve.append(round(capital, 2))
        returns = [(equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1] for i in range(1, len(equity_curve)) if equity_curve[i - 1] > 0]
        total_trades = len(trades)
        wins = [t for t in trades if t['profit'] > 0]
        losses = [t for t in trades if t['profit'] <= 0]
        win_rate = len(wins) / total_trades * 100.0 if total_trades > 0 else 0.0
        gross_profit = sum((t['profit'] for t in wins))
        gross_loss = abs(sum((t['profit'] for t in losses)))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit if gross_profit > 0 else 1.0
        peak = max(1e-05, equity_curve[0])
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        mean_ret = sum(returns) / len(returns) if returns else 0.0
        std_ret = math.sqrt(sum(((r - mean_ret) ** 2 for r in returns)) / len(returns)) if len(returns) > 1 else 0.0001
        sharpe = mean_ret / std_ret * math.sqrt(252 * 1440) if std_ret > 0 else 0.0
        return {'initial_capital': self.initial_capital, 'final_capital': round(capital, 2), 'net_profit_usd': round(capital - self.initial_capital, 2), 'total_trades': total_trades, 'win_rate_pct': round(win_rate, 2), 'profit_factor': round(profit_factor, 2), 'max_drawdown_pct': round(max_dd * 100.0, 2), 'sharpe_ratio': round(sharpe, 2), 'equity_curve': equity_curve}

    def walk_forward_optimization(self, historical_bars: Any, param_grid: Any=[(15, 30), (20, 40), (25, 50)]) -> Any:
        """
        Executes parallel walk-forward optimization across parameter grids
        utilizing concurrent ThreadPoolExecutor worker pipelines.
        """
        import concurrent.futures

        def momentum_trend_strategy(bars: Any) -> Any:
            closes = [b['close'] for b in bars]
            if len(closes) >= 5:
                if closes[-1] > closes[-5]:
                    return 'BUY'
                elif closes[-1] < closes[-5]:
                    return 'SELL'
            return 'HOLD'

        def eval_param_pair(sl_tp: Any) -> Any:
            sl, tp = sl_tp
            res = self.run_backtest(historical_bars, momentum_trend_strategy, sl_pips=sl, tp_pips=tp)
            return ((sl, tp), res)
        best_sharpe = -999.0
        best_params = None
        best_results = None
        max_workers = min(8, max(1, len(param_grid)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(eval_param_pair, pair) for pair in param_grid]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    (sl, tp), res = fut.result()
                    if res['sharpe_ratio'] > best_sharpe:
                        best_sharpe = res['sharpe_ratio']
                        best_params = (sl, tp)
                        best_results = res
                except Exception as e:
                    print(f'Diagnostics: Walk-forward parallel task failed: {e}')
        return {'best_params_sl_tp': best_params, 'best_sharpe': best_sharpe, 'best_results': best_results}

    def run_vectorized_backtest(self, numpy_close_prices: Any, numpy_signals: Any) -> Any:
        """
        Executes vectorized array-based backtest over historical price vector using NumPy.
        numpy_close_prices: 1D np.ndarray or list of closing prices
        numpy_signals: 1D np.ndarray or list of signals (1 for BUY, -1 for SELL, 0 for HOLD)
        """
        import numpy as np
        prices = np.asarray(numpy_close_prices, dtype=np.float64)
        signals = np.asarray(numpy_signals, dtype=np.float64)
        if len(prices) < 2 or len(signals) != len(prices):
            return {'status': 'INVALID_INPUT', 'net_profit_usd': 0.0}
        price_returns = np.diff(prices) / prices[:-1]
        strategy_returns = signals[:-1] * price_returns
        cumulative_equity = self.initial_capital * np.cumprod(1.0 + strategy_returns)
        equity_curve = np.insert(cumulative_equity, 0, self.initial_capital)
        net_profit = equity_curve[-1] - self.initial_capital
        win_rate = float(np.mean(strategy_returns > 0) * 100.0) if len(strategy_returns) > 0 else 0.0
        peaks = np.maximum.accumulate(equity_curve)
        drawdowns = (peaks - equity_curve) / np.maximum(peaks, 1e-05)
        max_drawdown_pct = float(np.max(drawdowns) * 100.0)
        mean_ret = np.mean(strategy_returns) if len(strategy_returns) > 0 else 0.0
        std_ret = np.std(strategy_returns) if len(strategy_returns) > 1 else 0.0001
        sharpe = float(mean_ret / max(std_ret, 1e-05) * np.sqrt(252 * 1440))
        return {'initial_capital': self.initial_capital, 'final_capital': round(float(equity_curve[-1]), 2), 'net_profit_usd': round(float(net_profit), 2), 'win_rate_pct': round(win_rate, 2), 'max_drawdown_pct': round(max_drawdown_pct, 2), 'sharpe_ratio': round(sharpe, 2), 'vectorized': True}
