"""
Data Validator Module
Validates external data feeds for quality, freshness, completeness, and consistency.
"""

from datetime import datetime as dt
from typing import List, Dict, Any, Optional
import statistics


class DataValidator:
    """
    Validates market data from external feeds.
    Ensures data quality before it's used in trading decisions.
    """
    
    def __init__(self):
        # Validation thresholds
        self.max_age_seconds = 300  # Data older than 5 minutes is stale
        self.min_data_points = 10  # Minimum required data points
        self.max_price_jump_pct = 0.10  # Max 10% price jump allowed
        self.min_price = 0.0001  # Minimum reasonable price
        self.max_price = 1000000  # Maximum reasonable price
    
    def validate_prices(self, prices: List[float], symbol: str = None) -> Dict[str, Any]:
        """
        Validate a list of price data.
        
        Args:
            prices: List of price values
            symbol: Trading symbol (for context)
            
        Returns:
            Validation result dict with:
            - valid: bool
            - score: float (0-100)
            - errors: list of error messages
            - warnings: list of warning messages
        """
        result = {
            'valid': True,
            'score': 100.0,
            'errors': [],
            'warnings': []
        }
        
        # Check if prices is empty
        if not prices:
            result['valid'] = False
            result['score'] = 0.0
            result['errors'].append("No price data provided")
            return result
        
        # Check minimum data points
        if len(prices) < self.min_data_points:
            result['valid'] = False
            result['score'] -= 50
            result['errors'].append(f"Insufficient data points: {len(prices)} < {self.min_data_points}")
        
        # Check for None/NaN values
        if any(p is None or (isinstance(p, float) and (p != p)) for p in prices):
            result['valid'] = False
            result['score'] -= 30
            result['errors'].append("Data contains None or NaN values")
            return result  # Return early if data has None/NaN
        
        # Check price range
        for i, price in enumerate(prices):
            if not isinstance(price, (int, float)):
                result['valid'] = False
                result['score'] -= 20
                result['errors'].append(f"Invalid price type at index {i}: {type(price)}")
                continue
            
            if price < self.min_price or price > self.max_price:
                result['valid'] = False
                result['score'] -= 20
                result['errors'].append(f"Price out of reasonable range at index {i}: {price}")
        
        # Check for sudden price jumps
        if len(prices) > 1:
            for i in range(1, len(prices)):
                if prices[i] == 0:
                    continue  # Skip zero prices
                
                jump_pct = abs(prices[i] - prices[i-1]) / prices[i-1]
                if jump_pct > self.max_price_jump_pct:
                    result['valid'] = False
                    result['score'] -= 15
                    result['errors'].append(
                        f"Excessive price jump at index {i}: {jump_pct:.2%} "
                        f"({prices[i-1]:.5f} -> {prices[i]:.5f})"
                    )
        
        # Check for duplicates
        if len(prices) > 1:
            duplicates = len(prices) - len(set(prices))
            if duplicates > 0:
                result['score'] -= min(10, duplicates)
                result['warnings'].append(f"Found {duplicates} duplicate price values")
        
        # Ensure score is within bounds
        result['score'] = max(0.0, min(100.0, result['score']))
        
        return result
    
    def validate_timestamp(self, timestamp: Optional[str], max_age_seconds: int = None) -> Dict[str, Any]:
        """
        Validate data timestamp for freshness.
        
        Args:
            timestamp: ISO format timestamp string
            max_age_seconds: Maximum allowed age in seconds (uses default if None)
            
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'score': 100.0,
            'errors': [],
            'warnings': []
        }
        
        if timestamp is None:
            result['valid'] = False
            result['score'] = 0.0
            result['errors'].append("No timestamp provided")
            return result
        
        try:
            # Parse timestamp
            if isinstance(timestamp, str):
                data_time = dt.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                data_time = timestamp
            
            # Calculate age
            age_seconds = (dt.now() - data_time).total_seconds()
            
            # Check if data is stale
            max_age = max_age_seconds or self.max_age_seconds
            if age_seconds > max_age:
                result['valid'] = False
                result['score'] = max(0.0, 100.0 - (age_seconds / max_age) * 100)
                result['errors'].append(f"Data is stale: {age_seconds:.0f} seconds old (max: {max_age}s)")
            elif age_seconds > max_age * 0.5:
                result['score'] -= 20
                result['warnings'].append(f"Data is aging: {age_seconds:.0f} seconds old")
            
        except Exception as e:
            result['valid'] = False
            result['score'] = 0.0
            result['errors'].append(f"Invalid timestamp format: {e}")
        
        return result
    
    def validate_completeness(self, data: Dict[str, Any], required_fields: List[str]) -> Dict[str, Any]:
        """
        Validate that data contains all required fields.
        
        Args:
            data: Data dictionary
            required_fields: List of required field names
            
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'score': 100.0,
            'errors': [],
            'warnings': []
        }
        
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            result['valid'] = False
            result['score'] -= len(missing_fields) * 20
            result['errors'].append(f"Missing required fields: {', '.join(missing_fields)}")
        
        return result
    
    def validate_data_consistency(self, ohlcv_data: List[Dict[str, float]]) -> Dict[str, Any]:
        """
        Validate OHLCV data for consistency (e.g., high >= low, close within range).
        
        Args:
            ohlcv_data: List of OHLCV dictionaries
            
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'score': 100.0,
            'errors': [],
            'warnings': []
        }
        
        for i, candle in enumerate(ohlcv_data):
            try:
                open_price = candle.get('open', 0)
                high_price = candle.get('high', 0)
                low_price = candle.get('low', 0)
                close_price = candle.get('close', 0)
                
                # Check high >= low
                if high_price < low_price:
                    result['valid'] = False
                    result['score'] -= 30
                    result['errors'].append(
                        f"High < Low at index {i}: {high_price} < {low_price}"
                    )
                
                # Check close within range
                if close_price > high_price or close_price < low_price:
                    result['valid'] = False
                    result['score'] -= 30
                    result['errors'].append(
                        f"Close outside range at index {i}: {close_price} "
                        f"(low: {low_price}, high: {high_price})"
                    )
                
                # Check reasonable candle ranges
                if high_price > 0 and low_price > 0:
                    range_pct = (high_price - low_price) / low_price
                    if range_pct > 0.20:  # More than 20% range is suspicious
                        result['score'] -= 10
                        result['warnings'].append(
                            f"Large candle range at index {i}: {range_pct:.2%}"
                        )
                
            except Exception as e:
                result['valid'] = False
                result['score'] -= 20
                result['errors'].append(f"Error validating candle {i}: {e}")
        
        return result
    
    def calculate_data_quality_score(self, validations: List[Dict[str, Any]]) -> float:
        """
        Calculate overall data quality score from multiple validations.
        
        Args:
            validations: List of validation result dicts
            
        Returns:
            Overall quality score (0-100)
        """
        if not validations:
            return 0.0
        
        scores = [v.get('score', 0.0) for v in validations]
        return statistics.mean(scores)


# Global validator instance
_data_validator = None

def get_data_validator() -> DataValidator:
    """Get the global data validator instance."""
    global _data_validator
    if _data_validator is None:
        _data_validator = DataValidator()
    return _data_validator
