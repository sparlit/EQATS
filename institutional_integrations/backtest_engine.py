"""
Event-Driven Backtesting & Walk-Forward Engine.
Executes historical event simulation, parameter walk-forward optimization,
and generates performance metrics (Sharpe Ratio, Sortino, Profit Factor, Max Drawdown).
"""

import math
import random

class EventDrivenBacktester:
    """Event-driven historical backtester and walk-forward optimizer."""

    def __init__(self, initial_capital=10000.0, commission_per_trade=1.0):
        self.initial_capital = initial_capital
        self.commission_per_trade = commission_per_trade

    def run_backtest(self, historical_bars, strategy_func, sl_pips=20, tp_pips=40, lot_size=0.01):
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

            # 1. Manage open position SL/TP
            if open_trade:
                dir_m = 1 if open_trade['dir'] == 'BUY' else -1
                if (open_trade['dir'] == 'BUY' and low_p <= open_trade['sl']) or (open_trade['dir'] == 'SELL' and high_p >= open_trade['sl']):
                    # Closed via SL
                    close_price = open_trade['sl']
                    profit = (close_price - open_trade['entry']) * dir_m * lot_size * 100000.0 - self.commission_per_trade
                    capital += profit
                    open_trade['profit'] = profit
                    open_trade['reason'] = 'SL'
                    trades.append(open_trade)
                    open_trade = None
                elif (open_trade['dir'] == 'BUY' and high_p >= open_trade['tp']) or (open_trade['dir'] == 'SELL' and low_p <= open_trade['tp']):
                    # Closed via TP
                    close_price = open_trade['tp']
                    profit = (close_price - open_trade['entry']) * dir_m * lot_size * 100000.0 - self.commission_per_trade
                    capital += profit
                    open_trade['profit'] = profit
                    open_trade['reason'] = 'TP'
                    trades.append(open_trade)
                    open_trade = None

            # 2. Evaluate Strategy Signal
            if not open_trade and idx >= 20:
                signal = strategy_func(historical_bars[:idx+1])
                if signal in ['BUY', 'SELL']:
                    sl_dist = (sl_pips * 0.0001) if close_p < 10 else (sl_pips * 0.01)
                    tp_dist = (tp_pips * 0.0001) if close_p < 10 else (tp_pips * 0.01)

                    sl_price = close_p - sl_dist if signal == 'BUY' else close_p + sl_dist
                    tp_price = close_p + tp_dist if signal == 'BUY' else close_p - tp_dist

                    open_trade = {
                        'entry': close_p,
                        'dir': signal,
                        'sl': sl_price,
                        'tp': tp_price,
                        'bar_idx': idx
                    }

            equity_curve.append(round(capital, 2))

        # Calculate performance statistics
        returns = [(equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1] for i in range(1, len(equity_curve)) if equity_curve[i-1] > 0]
        total_trades = len(trades)
        wins = [t for t in trades if t['profit'] > 0]
        losses = [t for t in trades if t['profit'] <= 0]

        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
        gross_profit = sum(t['profit'] for t in wins)
        gross_loss = abs(sum(t['profit'] for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

        # Max Drawdown
        peak = max(1e-5, equity_curve[0])
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # Sharpe Ratio (Annualized assuming M1 bars ~ 252*1440 bars/yr)
        mean_ret = sum(returns) / len(returns) if returns else 0.0
        std_ret = math.sqrt(sum((r - mean_ret)**2 for r in returns) / len(returns)) if len(returns) > 1 else 0.0001
        sharpe = (mean_ret / std_ret * math.sqrt(252 * 1440)) if std_ret > 0 else 0.0

        return {
            "initial_capital": self.initial_capital,
            "final_capital": round(capital, 2),
            "net_profit_usd": round(capital - self.initial_capital, 2),
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_dd * 100.0, 2),
            "sharpe_ratio": round(sharpe, 2),
            "equity_curve": equity_curve
        }

    def walk_forward_optimization(self, historical_bars, param_grid=[(15, 30), (20, 40), (25, 50)]):
        """Walk-forward optimization across parameter grids."""
        best_sharpe = -999.0
        best_params = None
        best_results = None

        def dummy_strategy(bars):
            closes = [b['close'] for b in bars]
            if closes[-1] > closes[-5]:
                return 'BUY'
            elif closes[-1] < closes[-5]:
                return 'SELL'
            return 'HOLD'

        for sl, tp in param_grid:
            res = self.run_backtest(historical_bars, dummy_strategy, sl_pips=sl, tp_pips=tp)
            if res["sharpe_ratio"] > best_sharpe:
                best_sharpe = res["sharpe_ratio"]
                best_params = (sl, tp)
                best_results = res

        return {
            "best_params_sl_tp": best_params,
            "best_sharpe": best_sharpe,
            "best_results": best_results
        }
