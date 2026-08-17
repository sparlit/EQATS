"""
Risk Controls Module
Implements pre-trade risk checks to prevent dangerous orders.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime as dt


class RiskLimitExceeded(Exception):
    """Raised when a risk limit is exceeded."""
    pass


class RiskControls:
    """
    Pre-trade risk checks to prevent dangerous orders.
    Validates orders against risk limits before submission.
    """
    
    def __init__(self):
        # Risk limits (configurable)
        self.max_lot_size = 10.0  # Maximum lot size per order
        self.max_position_size = 50.0  # Maximum position size per symbol
        self.max_total_exposure = 100.0  # Maximum total exposure across all symbols
        self.max_price_deviation_pct = 0.05  # Max 5% price deviation from market
        self.max_daily_loss_pct = 0.10  # Max 10% daily loss
        self.max_drawdown_pct = 0.20  # Max 20% drawdown
        
        # Symbol-specific limits
        self.symbol_limits = {}
        
        # Daily tracking
        self.daily_pnl = 0.0
        self.daily_start_balance = 0.0
        self.current_balance = 0.0
        self.daily_trades = []
        
        # Position tracking
        self.positions = {}  # symbol -> total position size
    
    def set_symbol_limit(self, symbol: str, max_lot: float, max_position: float):
        """Set custom limits for a specific symbol."""
        self.symbol_limits[symbol.upper()] = {
            'max_lot': max_lot,
            'max_position': max_position
        }
    
    def check_lot_size(self, symbol: str, lot_size: float) -> Dict[str, Any]:
        """
        Validate lot size against limits.
        
        Args:
            symbol: Trading symbol
            lot_size: Order lot size
            
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'error': None,
            'limit': None
        }
        
        # Check general max lot size
        if lot_size > self.max_lot_size:
            result['valid'] = False
            result['error'] = f"Lot size {lot_size} exceeds maximum {self.max_lot_size}"
            result['limit'] = self.max_lot_size
            return result
        
        # Check symbol-specific limit
        sym_upper = symbol.upper()
        if sym_upper in self.symbol_limits:
            sym_limit = self.symbol_limits[sym_upper]['max_lot']
            if lot_size > sym_limit:
                result['valid'] = False
                result['error'] = f"Lot size {lot_size} exceeds symbol limit {sym_limit} for {symbol}"
                result['limit'] = sym_limit
                return result
        
        # Check minimum lot size
        if lot_size < 0.01:
            result['valid'] = False
            result['error'] = f"Lot size {lot_size} below minimum 0.01"
            return result
        
        return result
    
    def check_price_deviation(self, symbol: str, order_price: float, market_price: float) -> Dict[str, Any]:
        """
        Validate price deviation from market.
        
        Args:
            symbol: Trading symbol
            order_price: Order price
            market_price: Current market price
            
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'error': None,
            'deviation_pct': None
        }
        
        if market_price == 0:
            result['valid'] = False
            result['error'] = "Market price is zero"
            return result
        
        deviation_pct = abs(order_price - market_price) / market_price
        result['deviation_pct'] = deviation_pct
        
        if deviation_pct > self.max_price_deviation_pct:
            result['valid'] = False
            result['error'] = f"Price deviation {deviation_pct:.2%} exceeds maximum {self.max_price_deviation_pct:.2%}"
            return result
        
        return result
    
    def check_position_limit(self, symbol: str, lot_size: float, order_type: str) -> Dict[str, Any]:
        """
        Validate position size against limits.
        
        Args:
            symbol: Trading symbol
            lot_size: Order lot size
            order_type: 'BUY' or 'SELL'
            
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'error': None,
            'current_position': None,
            'new_position': None,
            'limit': None
        }
        
        sym_upper = symbol.upper()
        current_position = self.positions.get(sym_upper, 0.0)
        
        # Calculate new position after order
        if order_type.upper() == 'BUY':
            new_position = current_position + lot_size
        else:
            new_position = current_position - lot_size
        
        result['current_position'] = current_position
        result['new_position'] = new_position
        
        # Check general max position size
        if abs(new_position) > self.max_position_size:
            result['valid'] = False
            result['error'] = f"New position {new_position} exceeds maximum {self.max_position_size}"
            result['limit'] = self.max_position_size
            return result
        
        # Check symbol-specific limit
        if sym_upper in self.symbol_limits:
            sym_limit = self.symbol_limits[sym_upper]['max_position']
            if abs(new_position) > sym_limit:
                result['valid'] = False
                result['error'] = f"New position {new_position} exceeds symbol limit {sym_limit} for {symbol}"
                result['limit'] = sym_limit
                return result
        
        return result
    
    def check_total_exposure(self, symbol: str, lot_size: float) -> Dict[str, Any]:
        """
        Validate total exposure across all symbols.
        
        Args:
            symbol: Trading symbol
            lot_size: Order lot size
            
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'error': None,
            'current_exposure': None,
            'new_exposure': None,
            'limit': None
        }
        
        # Calculate current total exposure
        current_exposure = sum(abs(pos) for pos in self.positions.values())
        new_exposure = current_exposure + lot_size
        
        result['current_exposure'] = current_exposure
        result['new_exposure'] = new_exposure
        
        if new_exposure > self.max_total_exposure:
            result['valid'] = False
            result['error'] = f"New exposure {new_exposure} exceeds maximum {self.max_total_exposure}"
            result['limit'] = self.max_total_exposure
            return result
        
        return result
    
    def check_daily_loss_limit(self) -> Dict[str, Any]:
        """
        Validate daily loss limit.
        
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'error': None,
            'daily_pnl': None,
            'daily_pnl_pct': None,
            'limit': None
        }
        
        if self.daily_start_balance == 0:
            return result
        
        daily_pnl_pct = self.daily_pnl / self.daily_start_balance
        result['daily_pnl'] = self.daily_pnl
        result['daily_pnl_pct'] = daily_pnl_pct
        
        # Check if loss exceeds limit
        if daily_pnl_pct < -self.max_daily_loss_pct:
            result['valid'] = False
            result['error'] = f"Daily loss {daily_pnl_pct:.2%} exceeds maximum {self.max_daily_loss_pct:.2%}"
            result['limit'] = self.max_daily_loss_pct
            return result
        
        return result
    
    def check_drawdown_limit(self) -> Dict[str, Any]:
        """
        Validate drawdown limit.
        
        Returns:
            Validation result dict
        """
        result = {
            'valid': True,
            'error': None,
            'current_drawdown': None,
            'limit': None
        }
        
        if self.daily_start_balance == 0:
            return result
        
        current_drawdown = (self.daily_start_balance - self.current_balance) / self.daily_start_balance
        result['current_drawdown'] = current_drawdown
        
        if current_drawdown > self.max_drawdown_pct:
            result['valid'] = False
            result['error'] = f"Drawdown {current_drawdown:.2%} exceeds maximum {self.max_drawdown_pct:.2%}"
            result['limit'] = self.max_drawdown_pct
            return result
        
        return result
    
    def update_daily_pnl(self, pnl: float):
        """Update daily P&L."""
        self.daily_pnl += pnl
        self.daily_trades.append({
            'pnl': pnl,
            'timestamp': dt.now().isoformat()
        })
    
    def update_position(self, symbol: str, lot_size: float, order_type: str):
        """Update position after order execution."""
        sym_upper = symbol.upper()
        current = self.positions.get(sym_upper, 0.0)
        
        if order_type.upper() == 'BUY':
            self.positions[sym_upper] = current + lot_size
        else:
            self.positions[sym_upper] = current - lot_size
        
        # Remove position if closed
        if abs(self.positions[sym_upper]) < 0.001:
            del self.positions[sym_upper]
    
    def update_balance(self, balance: float):
        """Update current balance."""
        self.current_balance = balance
    
    def reset_daily(self, start_balance: float):
        """Reset daily tracking with new start balance."""
        self.daily_start_balance = start_balance
        self.current_balance = start_balance
        self.daily_pnl = 0.0
        self.daily_trades = []
    
    def validate_order(self, symbol: str, order_type: str, lot_size: float, 
                     price: Optional[float] = None, market_price: Optional[float] = None) -> Dict[str, Any]:
        """
        Run all pre-trade risk checks on an order.
        
        Args:
            symbol: Trading symbol
            order_type: 'BUY' or 'SELL'
            lot_size: Order lot size
            price: Order price (optional)
            market_price: Current market price (optional)
            
        Returns:
            Comprehensive validation result
        """
        result = {
            'valid': True,
            'checks': [],
            'errors': []
        }
        
        # Check lot size
        lot_check = self.check_lot_size(symbol, lot_size)
        result['checks'].append({'check': 'lot_size', 'result': lot_check})
        if not lot_check['valid']:
            result['valid'] = False
            result['errors'].append(lot_check['error'])
        
        # Check position limit
        pos_check = self.check_position_limit(symbol, lot_size, order_type)
        result['checks'].append({'check': 'position_limit', 'result': pos_check})
        if not pos_check['valid']:
            result['valid'] = False
            result['errors'].append(pos_check['error'])
        
        # Check total exposure
        exp_check = self.check_total_exposure(symbol, lot_size)
        result['checks'].append({'check': 'total_exposure', 'result': exp_check})
        if not exp_check['valid']:
            result['valid'] = False
            result['errors'].append(exp_check['error'])
        
        # Check price deviation if prices provided
        if price is not None and market_price is not None:
            price_check = self.check_price_deviation(symbol, price, market_price)
            result['checks'].append({'check': 'price_deviation', 'result': price_check})
            if not price_check['valid']:
                result['valid'] = False
                result['errors'].append(price_check['error'])
        
        # Check daily loss limit
        loss_check = self.check_daily_loss_limit()
        result['checks'].append({'check': 'daily_loss', 'result': loss_check})
        if not loss_check['valid']:
            result['valid'] = False
            result['errors'].append(loss_check['error'])
        
        # Check drawdown limit
        drawdown_check = self.check_drawdown_limit()
        result['checks'].append({'check': 'drawdown', 'result': drawdown_check})
        if not drawdown_check['valid']:
            result['valid'] = False
            result['errors'].append(drawdown_check['error'])
        
        return result
    
    def check_fat_finger(self, symbol: str, lot_size: float, price: Optional[float] = None,
                         market_price: Optional[float] = None, order_type: str = None) -> Dict[str, Any]:
        """
        Detect fat-finger errors (typing mistakes, UI errors).
        
        Args:
            symbol: Trading symbol
            lot_size: Order lot size
            price: Order price (optional)
            market_price: Current market price (optional)
            order_type: 'BUY' or 'SELL' (optional)
            
        Returns:
            Fat-finger detection result
        """
        result = {
            'suspicious': False,
            'risk_level': 'LOW',
            'warnings': [],
            'confidence': 0.0
        }
        
        risk_score = 0.0
        warnings = []
        
        # Check 1: Unusually large lot size
        if lot_size > 1.0:
            risk_score += 20
            warnings.append(f"Large lot size: {lot_size}")
        if lot_size > 5.0:
            risk_score += 30
            warnings.append(f"Very large lot size: {lot_size}")
        
        # Check 2: Round number lot size (e.g., 10.0, 100.0) - suspicious
        if lot_size in [1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]:
            risk_score += 15
            warnings.append(f"Round number lot size: {lot_size}")
        
        # Check 3: Price anomaly if provided
        if price is not None and market_price is not None:
            price_diff_pct = abs(price - market_price) / market_price
            if price_diff_pct > 0.02:  # >2% deviation
                risk_score += 25
                warnings.append(f"Price deviation: {price_diff_pct:.2%}")
            if price_diff_pct > 0.05:  # >5% deviation
                risk_score += 35
                warnings.append(f"Large price deviation: {price_diff_pct:.2%}")
        
        # Check 4: Repeated digit patterns (e.g., 111, 222)
        lot_str = str(lot_size).replace('.', '')
        if len(lot_str) >= 3 and all(c == lot_str[0] for c in lot_str):
            risk_score += 20
            warnings.append(f"Repeated digit pattern: {lot_size}")
        
        # Check 5: Sequential digit patterns (e.g., 123, 456)
        if len(lot_str) >= 3:
            is_sequential = True
            for i in range(len(lot_str) - 1):
                if int(lot_str[i+1]) != int(lot_str[i]) + 1:
                    is_sequential = False
                    break
            if is_sequential:
                risk_score += 15
                warnings.append(f"Sequential digit pattern: {lot_size}")
        
        # Check 6: Unusual lot size for symbol
        sym_upper = symbol.upper()
        if "BTC" in sym_upper and lot_size > 1.0:
            risk_score += 25
            warnings.append(f"Large BTC lot size: {lot_size}")
        if "JPY" in sym_upper and lot_size > 10.0:
            risk_score += 20
            warnings.append(f"Large JPY lot size: {lot_size}")
        
        # Determine risk level
        if risk_score >= 70:
            result['risk_level'] = 'HIGH'
            result['suspicious'] = True
        elif risk_score >= 40:
            result['risk_level'] = 'MEDIUM'
            result['suspicious'] = True
        elif risk_score >= 20:
            result['risk_level'] = 'LOW'
        
        result['warnings'] = warnings
        result['confidence'] = min(100, risk_score)
        
        return result


# Global risk controls instance
_risk_controls = None

def get_risk_controls() -> RiskControls:
    """Get the global risk controls instance."""
    global _risk_controls
    if _risk_controls is None:
        _risk_controls = RiskControls()
    return _risk_controls
