"""
Data Freshness Monitoring Module
Monitors data freshness and detects stale feeds.
"""

from datetime import datetime as dt, timedelta
from typing import Dict, Any, Optional, List
import time


class DataFreshnessMonitor:
    """
    Monitors the freshness of data feeds and detects stale data.
    """
    
    def __init__(self):
        # Data timestamps
        self.data_timestamps = {}  # symbol -> last update timestamp
        
        # Freshness thresholds (in seconds)
        self.default_freshness_threshold = 60.0  # 1 minute default
        self.symbol_thresholds = {}  # symbol -> custom threshold
        
        # Staleness tracking
        self.stale_symbols = set()
        self.stale_history = []  # List of staleness events
        
        # Configuration
        self.enable_auto_detection = True
        self.warning_threshold_ratio = 0.5  # Warn at 50% of staleness threshold
    
    def set_freshness_threshold(self, symbol: str, threshold_seconds: float):
        """Set custom freshness threshold for a symbol."""
        self.symbol_thresholds[symbol.upper()] = threshold_seconds
    
    def get_freshness_threshold(self, symbol: str) -> float:
        """Get freshness threshold for a symbol."""
        return self.symbol_thresholds.get(symbol.upper(), self.default_freshness_threshold)
    
    def update_data_timestamp(self, symbol: str, timestamp: str = None):
        """
        Update the timestamp for a symbol's data.
        
        Args:
            symbol: Trading symbol
            timestamp: ISO format timestamp (default: now)
        """
        sym_upper = symbol.upper()
        if timestamp is None:
            timestamp = dt.now().isoformat()
        
        self.data_timestamps[sym_upper] = timestamp
        
        # Remove from stale set if it was stale
        if sym_upper in self.stale_symbols:
            self.stale_symbols.remove(sym_upper)
    
    def get_data_age(self, symbol: str) -> Optional[float]:
        """
        Get the age of data for a symbol in seconds.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Age in seconds, or None if no timestamp available
        """
        sym_upper = symbol.upper()
        if sym_upper not in self.data_timestamps:
            return None
        
        timestamp_str = self.data_timestamps[sym_upper]
        try:
            timestamp = dt.fromisoformat(timestamp_str)
            age = (dt.now() - timestamp).total_seconds()
            return max(0, age)  # Don't return negative ages
        except Exception as e:
            print(f"[ERROR] Error calculating data age for {symbol}: {e}")
            return None
    
    def is_data_fresh(self, symbol: str) -> bool:
        """
        Check if data for a symbol is fresh.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if data is fresh, False otherwise
        """
        age = self.get_data_age(symbol)
        if age is None:
            return False
        
        threshold = self.get_freshness_threshold(symbol)
        return age < threshold
    
    def is_data_stale(self, symbol: str) -> bool:
        """
        Check if data for a symbol is stale.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if data is stale, False otherwise
        """
        return not self.is_data_fresh(symbol)
    
    def check_freshness(self, symbol: str) -> Dict[str, Any]:
        """
        Perform comprehensive freshness check for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Freshness status dict
        """
        sym_upper = symbol.upper()
        age = self.get_data_age(symbol)
        threshold = self.get_freshness_threshold(symbol)
        
        result = {
            'symbol': sym_upper,
            'fresh': True,
            'stale': False,
            'warning': False,
            'age_seconds': age,
            'threshold_seconds': threshold,
            'age_ratio': None,
            'last_update': self.data_timestamps.get(sym_upper),
            'time_until_stale': None
        }
        
        if age is None:
            result['fresh'] = False
            result['stale'] = True
            result['warning'] = True
            result['error'] = "No timestamp available"
            return result
        
        result['age_ratio'] = age / threshold if threshold > 0 else 0
        result['time_until_stale'] = max(0, threshold - age)
        
        # Check staleness
        if age >= threshold:
            result['fresh'] = False
            result['stale'] = True
            result['warning'] = True
            
            # Add to stale set
            self.stale_symbols.add(sym_upper)
            
            # Record staleness event
            self.stale_history.append({
                'symbol': sym_upper,
                'timestamp': dt.now().isoformat(),
                'age': age,
                'threshold': threshold
            })
        elif age >= threshold * self.warning_threshold_ratio:
            result['warning'] = True
        
        return result
    
    def check_all_symbols(self) -> Dict[str, Any]:
        """
        Check freshness for all tracked symbols.
        
        Returns:
            Summary of freshness status for all symbols
        """
        results = {}
        stale_count = 0
        warning_count = 0
        
        for symbol in self.data_timestamps.keys():
            result = self.check_freshness(symbol)
            results[symbol] = result
            
            if result['stale']:
                stale_count += 1
            elif result['warning']:
                warning_count += 1
        
        return {
            'total_symbols': len(self.data_timestamps),
            'fresh_count': len(self.data_timestamps) - stale_count - warning_count,
            'stale_count': stale_count,
            'warning_count': warning_count,
            'results': results,
            'timestamp': dt.now().isoformat()
        }
    
    def get_stale_symbols(self) -> List[str]:
        """Get list of currently stale symbols."""
        return list(self.stale_symbols)
    
    def get_freshness_summary(self) -> Dict[str, Any]:
        """
        Get a summary of data freshness status.
        
        Returns:
            Summary dict with overall freshness metrics
        """
        total_symbols = len(self.data_timestamps)
        if total_symbols == 0:
            return {
                'total_symbols': 0,
                'fresh_symbols': 0,
                'stale_symbols': 0,
                'warning_symbols': 0,
                'freshness_percentage': 100.0,
                'timestamp': dt.now().isoformat()
            }
        
        all_check = self.check_all_symbols()
        
        return {
            'total_symbols': total_symbols,
            'fresh_symbols': all_check['fresh_count'],
            'stale_symbols': all_check['stale_count'],
            'warning_symbols': all_check['warning_count'],
            'freshness_percentage': (all_check['fresh_count'] / total_symbols) * 100,
            'timestamp': dt.now().isoformat()
        }
    
    def should_block_trading(self, symbol: str = None) -> bool:
        """
        Determine if trading should be blocked due to stale data.
        
        Args:
            symbol: Specific symbol to check (optional, checks all if None)
            
        Returns:
            True if trading should be blocked, False otherwise
        """
        if symbol:
            return self.is_data_stale(symbol)
        else:
            # Block if any tracked symbol is stale
            return len(self.stale_symbols) > 0
    
    def get_staleness_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent staleness events.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of staleness events
        """
        return self.stale_history[-limit:]
    
    def clear_stale_symbols(self):
        """Clear the stale symbols set (for testing or manual reset)."""
        self.stale_symbols.clear()
    
    def reset_tracking(self):
        """Reset all tracking data."""
        self.data_timestamps.clear()
        self.stale_symbols.clear()
        self.stale_history.clear()


class DataQualityTracker:
    """
    Tracks data quality metrics beyond just freshness.
    """
    
    def __init__(self):
        # Quality metrics
        self.quality_scores = {}  # symbol -> quality score (0-100)
        self.error_counts = {}  # symbol -> error count
        self.gap_counts = {}  # symbol -> data gap count
        self.last_errors = {}  # symbol -> last error message
        
        # Thresholds
        self.min_quality_score = 70.0  # Minimum acceptable quality
        self.max_error_rate = 0.1  # Maximum 10% error rate
    
    def update_quality_score(self, symbol: str, score: float):
        """Update quality score for a symbol."""
        sym_upper = symbol.upper()
        self.quality_scores[sym_upper] = max(0, min(100, score))
    
    def record_error(self, symbol: str, error_message: str):
        """Record an error for a symbol."""
        sym_upper = symbol.upper()
        self.error_counts[sym_upper] = self.error_counts.get(sym_upper, 0) + 1
        self.last_errors[sym_upper] = error_message
    
    def record_gap(self, symbol: str):
        """Record a data gap for a symbol."""
        sym_upper = symbol.upper()
        self.gap_counts[sym_upper] = self.gap_counts.get(sym_upper, 0) + 1
    
    def get_quality_summary(self, symbol: str) -> Dict[str, Any]:
        """
        Get quality summary for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Quality summary dict
        """
        sym_upper = symbol.upper()
        
        return {
            'symbol': sym_upper,
            'quality_score': self.quality_scores.get(sym_upper, 100.0),
            'error_count': self.error_counts.get(sym_upper, 0),
            'gap_count': self.gap_counts.get(sym_upper, 0),
            'last_error': self.last_errors.get(sym_upper),
            'acceptable': self.quality_scores.get(sym_upper, 100.0) >= self.min_quality_score
        }
    
    def is_data_acceptable(self, symbol: str) -> bool:
        """
        Check if data quality is acceptable for trading.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if data is acceptable, False otherwise
        """
        sym_upper = symbol.upper()
        quality_score = self.quality_scores.get(sym_upper, 100.0)
        return quality_score >= self.min_quality_score


# Global instances
_freshness_monitor = None
_quality_tracker = None

def get_freshness_monitor() -> DataFreshnessMonitor:
    """Get the global freshness monitor instance."""
    global _freshness_monitor
    if _freshness_monitor is None:
        _freshness_monitor = DataFreshnessMonitor()
    return _freshness_monitor

def get_quality_tracker() -> DataQualityTracker:
    """Get the global quality tracker instance."""
    global _quality_tracker
    if _quality_tracker is None:
        _quality_tracker = DataQualityTracker()
    return _quality_tracker
