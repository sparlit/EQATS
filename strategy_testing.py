"""
Strategy Testing Module
Provides strategy testing and comparison capabilities.
"""

from typing import Dict, Any, List, Callable, Optional
from dataclasses import dataclass, field
import json
from backtesting_framework import BacktestEngine, BacktestResult


@dataclass
class StrategyTestResult:
    """Result of testing a single strategy."""
    strategy_name: str
    parameters: Dict[str, Any]
    backtest_result: BacktestResult
    passed: bool = False
    pass_criteria: Dict[str, Any] = field(default_factory=dict)


class StrategyTester:
    """
    Tests trading strategies against various criteria.
    """
    
    def __init__(self):
        self.test_results = []
        self.pass_criteria = {
            'min_win_rate': 0.40,  # 40% minimum win rate
            'max_drawdown': 0.20,  # 20% maximum drawdown
            'min_profit_factor': 1.5,  # 1.5 minimum profit factor
            'min_sharpe_ratio': 1.0  # 1.0 minimum Sharpe ratio
        }
    
    def set_pass_criteria(self, criteria: Dict[str, Any]):
        """
        Set pass criteria for strategy testing.
        
        Args:
            criteria: Dictionary of criteria thresholds
        """
        self.pass_criteria.update(criteria)
    
    def test_strategy(self, strategy_name: str, strategy: Callable, 
                     parameters: Dict[str, Any], data: List[Dict[str, Any]],
                     initial_balance: float = 10000.0) -> StrategyTestResult:
        """
        Test a single strategy.
        
        Args:
            strategy_name: Name of the strategy
            strategy: Strategy function
            parameters: Strategy parameters
            data: Historical data for backtesting
            initial_balance: Starting balance
            
        Returns:
            StrategyTestResult
        """
        # Create backtest engine
        engine = BacktestEngine(initial_balance=initial_balance)
        engine.set_strategy_params(parameters)
        
        # Run backtest
        result = engine.run_backtest(data, strategy)
        
        # Check if strategy passes criteria
        passed = self._check_criteria(result)
        
        test_result = StrategyTestResult(
            strategy_name=strategy_name,
            parameters=parameters,
            backtest_result=result,
            passed=passed,
            pass_criteria=self.pass_criteria.copy()
        )
        
        self.test_results.append(test_result)
        
        return test_result
    
    def _check_criteria(self, result: BacktestResult) -> bool:
        """
        Check if backtest result meets pass criteria.
        
        Args:
            result: Backtest result
            
        Returns:
            True if passes all criteria
        """
        if result.win_rate < self.pass_criteria['min_win_rate']:
            return False
        
        if result.max_drawdown > self.pass_criteria['max_drawdown']:
            return False
        
        if result.profit_factor < self.pass_criteria['min_profit_factor']:
            return False
        
        if result.sharpe_ratio < self.pass_criteria['min_sharpe_ratio']:
            return False
        
        return True
    
    def compare_strategies(self, strategies: List[Dict[str, Any]], 
                         data: List[Dict[str, Any]]) -> List[StrategyTestResult]:
        """
        Compare multiple strategies.
        
        Args:
            strategies: List of strategy dicts with 'name', 'function', 'parameters'
            data: Historical data for backtesting
            
        Returns:
            List of test results
        """
        results = []
        
        for strategy_config in strategies:
            result = self.test_strategy(
                strategy_name=strategy_config['name'],
                strategy=strategy_config['function'],
                parameters=strategy_config['parameters'],
                data=data
            )
            results.append(result)
        
        # Sort by total P&L
        results.sort(key=lambda x: x.backtest_result.total_pnl, reverse=True)
        
        return results
    
    def get_best_strategy(self) -> Optional[StrategyTestResult]:
        """
        Get the best performing strategy from tested strategies.
        
        Returns:
            Best strategy test result or None
        """
        if not self.test_results:
            return None
        
        # Sort by total P&L
        sorted_results = sorted(self.test_results, 
                              key=lambda x: x.backtest_result.total_pnl, 
                              reverse=True)
        
        return sorted_results[0]
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of all strategy tests.
        
        Returns:
            Summary dict
        """
        if not self.test_results:
            return {'total_tests': 0, 'passed': 0, 'failed': 0}
        
        passed = sum(1 for r in self.test_results if r.passed)
        failed = len(self.test_results) - passed
        
        return {
            'total_tests': len(self.test_results),
            'passed': passed,
            'failed': failed,
            'pass_rate': passed / len(self.test_results),
            'best_strategy': self.get_best_strategy().strategy_name if self.get_best_strategy() else None,
            'criteria': self.pass_criteria
        }
    
    def save_results(self, filepath: str = "strategy_test_results.json") -> bool:
        """Save strategy test results to file."""
        try:
            data = {
                'summary': self.get_summary(),
                'criteria': self.pass_criteria,
                'results': [
                    {
                        'strategy_name': r.strategy_name,
                        'parameters': r.parameters,
                        'passed': r.passed,
                        'total_trades': r.backtest_result.total_trades,
                        'win_rate': r.backtest_result.win_rate,
                        'total_pnl': r.backtest_result.total_pnl,
                        'max_drawdown': r.backtest_result.max_drawdown,
                        'profit_factor': r.backtest_result.profit_factor,
                        'sharpe_ratio': r.backtest_result.sharpe_ratio
                    }
                    for r in self.test_results
                ]
            }
            
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save results: {e}")
            return False


# Example strategies for testing
def simple_buy_hold(data_point: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Simple buy and hold strategy."""
    return {
        'action': 'BUY',
        'symbol': 'EURUSD',
        'lot_size': 0.1,
        'sl': None,
        'tp': None
    }


def simple_sell_hold(data_point: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Simple sell and hold strategy."""
    return {
        'action': 'SELL',
        'symbol': 'EURUSD',
        'lot_size': 0.1,
        'sl': None,
        'tp': None
    }


def random_strategy(data_point: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Random trading strategy for testing."""
    import random
    action = random.choice(['BUY', 'SELL', 'HOLD'])
    
    if action == 'HOLD':
        return {'action': 'HOLD'}
    
    return {
        'action': action,
        'symbol': 'EURUSD',
        'lot_size': 0.1,
        'sl': None,
        'tp': None
    }


# Global strategy tester instance
_strategy_tester = None

def get_strategy_tester() -> StrategyTester:
    """Get the global strategy tester instance."""
    global _strategy_tester
    if _strategy_tester is None:
        _strategy_tester = StrategyTester()
    return _strategy_tester
