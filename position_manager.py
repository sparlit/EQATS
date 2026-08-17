"""
Position Tracking and Limits Module
Tracks trading positions and enforces position limits.
"""

from datetime import datetime as dt
from typing import Dict, Any, Optional, List
import json
import os


class Position:
    """
    Represents a trading position.
    """
    
    def __init__(self, symbol: str, direction: str, lot_size: float, 
                 open_price: float, open_time: str = None, ticket: str = None):
        self.symbol = symbol.upper()
        self.direction = direction.upper()  # BUY or SELL
        self.lot_size = lot_size
        self.open_price = open_price
        self.open_time = open_time or dt.now().isoformat()
        self.ticket = ticket
        
        # Current state
        self.current_price = open_price
        self.sl = None
        self.tp = None
        self.profit = 0.0
        self.is_closed = False
        self.close_time = None
        self.close_price = None
        self.close_reason = None
    
    def update_price(self, current_price: float):
        """Update current price and recalculate profit."""
        self.current_price = current_price
        self._calculate_profit()
    
    def _calculate_profit(self):
        """Calculate current profit based on price and direction."""
        if self.is_closed:
            return
        
        if self.direction == 'BUY':
            # Long position: profit = (current - open) * lot_size * multiplier
            # Assuming standard forex lot multiplier of 100,000
            self.profit = (self.current_price - self.open_price) * self.lot_size * 100000
        else:
            # Short position: profit = (open - current) * lot_size * multiplier
            self.profit = (self.open_price - self.current_price) * self.lot_size * 100000
    
    def close(self, close_price: float, reason: str = "MANUAL"):
        """Close the position."""
        self.close_price = close_price
        self.close_time = dt.now().isoformat()
        self.close_reason = reason
        self.is_closed = True
        self.current_price = close_price
        self._calculate_profit()
    
    def modify_sl_tp(self, sl: float = None, tp: float = None):
        """Modify stop loss and take profit levels."""
        if sl is not None:
            self.sl = sl
        if tp is not None:
            self.tp = tp
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert position to dictionary."""
        return {
            'symbol': self.symbol,
            'direction': self.direction,
            'lot_size': self.lot_size,
            'open_price': self.open_price,
            'open_time': self.open_time,
            'ticket': self.ticket,
            'current_price': self.current_price,
            'sl': self.sl,
            'tp': self.tp,
            'profit': self.profit,
            'is_closed': self.is_closed,
            'close_time': self.close_time,
            'close_price': self.close_price,
            'close_reason': self.close_reason
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        """Create position from dictionary."""
        position = cls(
            symbol=data['symbol'],
            direction=data['direction'],
            lot_size=data['lot_size'],
            open_price=data['open_price'],
            open_time=data.get('open_time'),
            ticket=data.get('ticket')
        )
        
        position.current_price = data.get('current_price', data['open_price'])
        position.sl = data.get('sl')
        position.tp = data.get('tp')
        position.profit = data.get('profit', 0.0)
        position.is_closed = data.get('is_closed', False)
        position.close_time = data.get('close_time')
        position.close_price = data.get('close_price')
        position.close_reason = data.get('close_reason')
        
        return position


class PositionManager:
    """
    Manages all trading positions with limit enforcement.
    """
    
    def __init__(self):
        self.positions = {}  # ticket -> Position
        self.symbol_positions = {}  # symbol -> list of tickets
        self.position_limits = {}  # symbol -> max lot size
        
        # Default limits
        self.default_max_position = 50.0  # Default max position per symbol
        self.max_total_exposure = 100.0  # Max total exposure across all symbols
    
    def set_position_limit(self, symbol: str, max_lot: float):
        """Set position limit for a specific symbol."""
        self.position_limits[symbol.upper()] = max_lot
    
    def get_position_limit(self, symbol: str) -> float:
        """Get position limit for a symbol."""
        return self.position_limits.get(symbol.upper(), self.default_max_position)
    
    def add_position(self, position: Position) -> bool:
        """Add a new position to tracking."""
        if position.ticket in self.positions:
            return False
        
        self.positions[position.ticket] = position
        
        # Track by symbol
        sym_upper = position.symbol
        if sym_upper not in self.symbol_positions:
            self.symbol_positions[sym_upper] = []
        self.symbol_positions[sym_upper].append(position.ticket)
        
        return True
    
    def remove_position(self, ticket: str) -> bool:
        """Remove a position from tracking."""
        if ticket not in self.positions:
            return False
        
        position = self.positions[ticket]
        sym_upper = position.symbol
        
        # Remove from symbol tracking
        if sym_upper in self.symbol_positions:
            self.symbol_positions[sym_upper].remove(ticket)
            if not self.symbol_positions[sym_upper]:
                del self.symbol_positions[sym_upper]
        
        del self.positions[ticket]
        return True
    
    def get_position(self, ticket: str) -> Optional[Position]:
        """Get a position by ticket."""
        return self.positions.get(ticket)
    
    def get_positions_by_symbol(self, symbol: str) -> List[Position]:
        """Get all positions for a specific symbol."""
        sym_upper = symbol.upper()
        if sym_upper not in self.symbol_positions:
            return []
        
        return [self.positions[ticket] for ticket in self.symbol_positions[sym_upper]]
    
    def get_open_positions(self) -> List[Position]:
        """Get all open (not closed) positions."""
        return [pos for pos in self.positions.values() if not pos.is_closed]
    
    def get_closed_positions(self) -> List[Position]:
        """Get all closed positions."""
        return [pos for pos in self.positions.values() if pos.is_closed]
    
    def get_all_positions(self) -> List[Position]:
        """Get all positions."""
        return list(self.positions.values())
    
    def calculate_symbol_exposure(self, symbol: str) -> float:
        """Calculate total exposure for a symbol (sum of open positions)."""
        positions = self.get_positions_by_symbol(symbol)
        exposure = 0.0
        
        for pos in positions:
            if not pos.is_closed:
                if pos.direction == 'BUY':
                    exposure += pos.lot_size
                else:
                    exposure -= pos.lot_size
        
        return abs(exposure)
    
    def calculate_total_exposure(self) -> float:
        """Calculate total exposure across all symbols."""
        positions = self.get_open_positions()
        exposure = 0.0
        
        for pos in positions:
            exposure += abs(pos.lot_size)
        
        return exposure
    
    def calculate_total_pnl(self) -> float:
        """Calculate total P&L from all open positions."""
        positions = self.get_open_positions()
        return sum(pos.profit for pos in positions)
    
    def check_position_limit(self, symbol: str, additional_lot: float, 
                           direction: str) -> Dict[str, Any]:
        """
        Check if adding a position would exceed limits.
        
        Args:
            symbol: Trading symbol
            additional_lot: Additional lot size
            direction: 'BUY' or 'SELL'
            
        Returns:
            Validation result
        """
        result = {
            'valid': True,
            'error': None,
            'current_exposure': None,
            'new_exposure': None,
            'limit': None
        }
        
        sym_upper = symbol.upper()
        current_exposure = self.calculate_symbol_exposure(sym_upper)
        
        # Calculate new exposure
        if direction.upper() == 'BUY':
            new_exposure = current_exposure + additional_lot
        else:
            new_exposure = current_exposure - additional_lot
        
        result['current_exposure'] = current_exposure
        result['new_exposure'] = abs(new_exposure)
        
        # Check symbol limit
        limit = self.get_position_limit(symbol)
        result['limit'] = limit
        
        if abs(new_exposure) > limit:
            result['valid'] = False
            result['error'] = f"New exposure {abs(new_exposure)} exceeds limit {limit} for {symbol}"
            return result
        
        # Check total exposure
        total_exposure = self.calculate_total_exposure()
        new_total = total_exposure + additional_lot
        
        if new_total > self.max_total_exposure:
            result['valid'] = False
            result['error'] = f"New total exposure {new_total} exceeds maximum {self.max_total_exposure}"
            return result
        
        return result
    
    def update_position_prices(self, prices: Dict[str, float]):
        """
        Update current prices for all open positions.
        
        Args:
            prices: Dictionary of symbol -> current price
        """
        for position in self.get_open_positions():
            if position.symbol in prices:
                position.update_price(prices[position.symbol])
    
    def get_position_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all positions.
        
        Returns:
            Summary dict with position counts, exposure, P&L, etc.
        """
        open_positions = self.get_open_positions()
        closed_positions = self.get_closed_positions()
        
        # Calculate by symbol
        symbol_summary = {}
        for pos in open_positions:
            sym = pos.symbol
            if sym not in symbol_summary:
                symbol_summary[sym] = {
                    'count': 0,
                    'total_lots': 0.0,
                    'total_profit': 0.0,
                    'long_positions': 0,
                    'short_positions': 0
                }
            
            summary = symbol_summary[sym]
            summary['count'] += 1
            summary['total_lots'] += pos.lot_size
            summary['total_profit'] += pos.profit
            
            if pos.direction == 'BUY':
                summary['long_positions'] += 1
            else:
                summary['short_positions'] += 1
        
        return {
            'total_open_positions': len(open_positions),
            'total_closed_positions': len(closed_positions),
            'total_exposure': self.calculate_total_exposure(),
            'total_pnl': self.calculate_total_pnl(),
            'symbols': symbol_summary,
            'timestamp': dt.now().isoformat()
        }
    
    def save_to_file(self, filepath: str = "positions.json") -> bool:
        """Save all positions to file."""
        try:
            positions_data = {
                ticket: position.to_dict()
                for ticket, position in self.positions.items()
            }
            with open(filepath, 'w') as f:
                json.dump(positions_data, f, indent=2)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save positions: {e}")
            return False
    
    def load_from_file(self, filepath: str = "positions.json") -> bool:
        """Load positions from file."""
        try:
            if not os.path.exists(filepath):
                return False
            
            with open(filepath, 'r') as f:
                positions_data = json.load(f)
            
            self.positions = {
                ticket: Position.from_dict(data)
                for ticket, data in positions_data.items()
            }
            
            # Rebuild symbol positions index
            self.symbol_positions = {}
            for ticket, position in self.positions.items():
                sym_upper = position.symbol
                if sym_upper not in self.symbol_positions:
                    self.symbol_positions[sym_upper] = []
                self.symbol_positions[sym_upper].append(ticket)
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load positions: {e}")
            return False


# Global position manager instance
_position_manager = None

def get_position_manager() -> PositionManager:
    """Get the global position manager instance."""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager
