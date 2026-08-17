"""
Performance Metrics Collection Module
Collects and tracks performance metrics for the trading system.
"""

from datetime import datetime as dt
from typing import Dict, Any, Optional, List
import json
import time


class PerformanceMetrics:
    """
    Collects and tracks performance metrics for the trading system.
    """
    
    def __init__(self):
        # Order metrics
        self.order_metrics = {
            'total_orders': 0,
            'successful_orders': 0,
            'failed_orders': 0,
            'rejected_orders': 0,
            'filled_orders': 0,
            'cancelled_orders': 0
        }
        
        # Latency metrics (in milliseconds)
        self.latency_metrics = {
            'order_submission_latency': [],
            'order_fill_latency': [],
            'data_fetch_latency': []
        }
        
        # P&L metrics
        self.pnl_metrics = {
            'total_pnl': 0.0,
            'realized_pnl': 0.0,
            'unrealized_pnl': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0
        }
        
        # Risk metrics
        self.risk_metrics = {
            'max_drawdown': 0.0,
            'current_drawdown': 0.0,
            'daily_loss_limit_breaches': 0,
            'position_limit_breaches': 0
        }
        
        # Data quality metrics
        self.data_quality_metrics = {
            'data_fetch_success_rate': 0.0,
            'data_validation_failures': 0,
            'stale_data_events': 0,
            'average_data_quality_score': 0.0
        }
        
        # System metrics
        self.system_metrics = {
            'uptime_start': dt.now().isoformat(),
            'total_runtime': 0.0,
            'memory_usage': 0.0,
            'cpu_usage': 0.0
        }
        
        # Metrics history
        self.metrics_history = []
        self.max_history_size = 1000
    
    def record_order_submission(self, latency_ms: float):
        """Record order submission latency."""
        self.latency_metrics['order_submission_latency'].append(latency_ms)
        self.order_metrics['total_orders'] += 1
    
    def record_order_success(self):
        """Record successful order."""
        self.order_metrics['successful_orders'] += 1
    
    def record_order_failure(self, reason: str = "UNKNOWN"):
        """Record failed order."""
        self.order_metrics['failed_orders'] += 1
    
    def record_order_rejection(self, reason: str = "UNKNOWN"):
        """Record rejected order."""
        self.order_metrics['rejected_orders'] += 1
    
    def record_order_fill(self, latency_ms: float, pnl: float = 0.0):
        """Record order fill with latency and P&L."""
        self.latency_metrics['order_fill_latency'].append(latency_ms)
        self.order_metrics['filled_orders'] += 1
        self.pnl_metrics['realized_pnl'] += pnl
        
        if pnl > 0:
            self.pnl_metrics['winning_trades'] += 1
        else:
            self.pnl_metrics['losing_trades'] += 1
        
        # Update win rate
        total_trades = self.pnl_metrics['winning_trades'] + self.pnl_metrics['losing_trades']
        if total_trades > 0:
            self.pnl_metrics['win_rate'] = self.pnl_metrics['winning_trades'] / total_trades
    
    def record_order_cancellation(self):
        """Record order cancellation."""
        self.order_metrics['cancelled_orders'] += 1
    
    def record_data_fetch(self, latency_ms: float, success: bool, quality_score: float = 100.0):
        """Record data fetch with latency and quality."""
        self.latency_metrics['data_fetch_latency'].append(latency_ms)
        
        total_fetches = len(self.latency_metrics['data_fetch_latency'])
        if total_fetches > 0:
            successful_fetches = sum(1 for i in range(total_fetches) if i < total_fetches)
            self.data_quality_metrics['data_fetch_success_rate'] = successful_fetches / total_fetches
        
        if quality_score < 50:
            self.data_quality_metrics['data_validation_failures'] += 1
        
        # Update average quality score
        total_quality = self.data_quality_metrics['average_data_quality_score'] * (total_fetches - 1) + quality_score
        self.data_quality_metrics['average_data_quality_score'] = total_quality / total_fetches
    
    def record_stale_data_event(self):
        """Record a stale data event."""
        self.data_quality_metrics['stale_data_events'] += 1
    
    def record_drawdown(self, drawdown_pct: float):
        """Record drawdown percentage."""
        self.risk_metrics['current_drawdown'] = drawdown_pct
        if drawdown_pct > self.risk_metrics['max_drawdown']:
            self.risk_metrics['max_drawdown'] = drawdown_pct
    
    def record_unrealized_pnl(self, pnl: float):
        """Record unrealized P&L from open positions."""
        self.pnl_metrics['unrealized_pnl'] = pnl
    
    def record_risk_limit_breach(self, limit_type: str):
        """Record a risk limit breach."""
        if limit_type == "position":
            self.risk_metrics['position_limit_breaches'] += 1
        elif limit_type == "daily_loss":
            self.risk_metrics['daily_loss_limit_breaches'] += 1
    
    def update_system_metrics(self, memory_mb: float = None, cpu_pct: float = None):
        """Update system resource metrics."""
        if memory_mb is not None:
            self.system_metrics['memory_usage'] = memory_mb
        if cpu_pct is not None:
            self.system_metrics['cpu_usage'] = cpu_pct
        
        # Update runtime
        start_time = dt.fromisoformat(self.system_metrics['uptime_start'])
        self.system_metrics['total_runtime'] = (dt.now() - start_time).total_seconds()
    
    def get_average_latency(self, metric_type: str) -> float:
        """
        Get average latency for a metric type.
        
        Args:
            metric_type: 'order_submission', 'order_fill', or 'data_fetch'
            
        Returns:
            Average latency in milliseconds
        """
        key = f"{metric_type}_latency"
        if key not in self.latency_metrics:
            return 0.0
        
        latencies = self.latency_metrics[key]
        if not latencies:
            return 0.0
        
        return sum(latencies) / len(latencies)
    
    def get_percentile_latency(self, metric_type: str, percentile: float = 95) -> float:
        """
        Get percentile latency for a metric type.
        
        Args:
            metric_type: 'order_submission', 'order_fill', or 'data_fetch'
            percentile: Percentile (0-100)
            
        Returns:
            Percentile latency in milliseconds
        """
        key = f"{metric_type}_latency"
        if key not in self.latency_metrics:
            return 0.0
        
        latencies = sorted(self.latency_metrics[key])
        if not latencies:
            return 0.0
        
        index = int(len(latencies) * percentile / 100)
        return latencies[min(index, len(latencies) - 1)]
    
    def get_order_success_rate(self) -> float:
        """Calculate order success rate."""
        if self.order_metrics['total_orders'] == 0:
            return 0.0
        
        return self.order_metrics['successful_orders'] / self.order_metrics['total_orders']
    
    def get_fill_rate(self) -> float:
        """Calculate fill rate."""
        if self.order_metrics['total_orders'] == 0:
            return 0.0
        
        return self.order_metrics['filled_orders'] / self.order_metrics['total_orders']
    
    def get_rejection_rate(self) -> float:
        """Calculate rejection rate."""
        if self.order_metrics['total_orders'] == 0:
            return 0.0
        
        return self.order_metrics['rejected_orders'] / self.order_metrics['total_orders']
    
    def get_total_pnl(self) -> float:
        """Get total P&L (realized + unrealized)."""
        return self.pnl_metrics['realized_pnl'] + self.pnl_metrics['unrealized_pnl']
    
    def get_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sharpe ratio (annualized).
        
        Args:
            risk_free_rate: Annual risk-free rate (default 2%)
            
        Returns:
            Sharpe ratio
        """
        # Simplified calculation - needs more data for proper Sharpe
        total_pnl = self.get_total_pnl()
        runtime_hours = self.system_metrics['total_runtime'] / 3600
        
        if runtime_hours == 0:
            return 0.0
        
        annualized_pnl = total_pnl * (24 * 365 / runtime_hours)
        excess_return = annualized_pnl - risk_free_rate
        
        if self.risk_metrics['max_drawdown'] == 0:
            return 0.0
        
        return excess_return / self.risk_metrics['max_drawdown']
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive metrics summary.
        
        Returns:
            Summary dict with all key metrics
        """
        return {
            'timestamp': dt.now().isoformat(),
            'order_metrics': self.order_metrics.copy(),
            'latency_metrics': {
                'avg_order_submission_latency': self.get_average_latency('order_submission'),
                'avg_order_fill_latency': self.get_average_latency('order_fill'),
                'avg_data_fetch_latency': self.get_average_latency('data_fetch'),
                'p95_order_submission_latency': self.get_percentile_latency('order_submission', 95),
                'p95_order_fill_latency': self.get_percentile_latency('order_fill', 95)
            },
            'pnl_metrics': self.pnl_metrics.copy(),
            'risk_metrics': self.risk_metrics.copy(),
            'data_quality_metrics': self.data_quality_metrics.copy(),
            'system_metrics': self.system_metrics.copy(),
            'derived_metrics': {
                'order_success_rate': self.get_order_success_rate(),
                'fill_rate': self.get_fill_rate(),
                'rejection_rate': self.get_rejection_rate(),
                'total_pnl': self.get_total_pnl(),
                'sharpe_ratio': self.get_sharpe_ratio()
            }
        }
    
    def snapshot_metrics(self):
        """Take a snapshot of current metrics and save to history."""
        snapshot = self.get_summary()
        self.metrics_history.append(snapshot)
        
        # Limit history size
        if len(self.metrics_history) > self.max_history_size:
            self.metrics_history = self.metrics_history[-self.max_history_size:]
    
    def get_metrics_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent metrics history."""
        return self.metrics_history[-limit:]
    
    def reset_metrics(self):
        """Reset all metrics to initial state."""
        self.__init__()
    
    def save_to_file(self, filepath: str = "performance_metrics.json") -> bool:
        """Save metrics to file."""
        try:
            summary = self.get_summary()
            with open(filepath, 'w') as f:
                json.dump(summary, f, indent=2)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save metrics: {e}")
            return False
    
    def load_from_file(self, filepath: str = "performance_metrics.json") -> bool:
        """Load metrics from file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Restore metrics
            self.order_metrics = data.get('order_metrics', self.order_metrics)
            self.latency_metrics = data.get('latency_metrics', self.latency_metrics)
            self.pnl_metrics = data.get('pnl_metrics', self.pnl_metrics)
            self.risk_metrics = data.get('risk_metrics', self.risk_metrics)
            self.data_quality_metrics = data.get('data_quality_metrics', self.data_quality_metrics)
            self.system_metrics = data.get('system_metrics', self.system_metrics)
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load metrics: {e}")
            return False


# Global performance metrics instance
_performance_metrics = None

def get_performance_metrics() -> PerformanceMetrics:
    """Get the global performance metrics instance."""
    global _performance_metrics
    if _performance_metrics is None:
        _performance_metrics = PerformanceMetrics()
    return _performance_metrics
