"""
Order Lifecycle Management Module
Implements order state machine with validation, persistence, and reconciliation.
"""

from enum import Enum
from datetime import datetime as dt
from typing import Dict, Any, Optional, List
import json
import os


class OrderState(Enum):
    """Order states for the state machine."""
    PENDING = "PENDING"           # Order created, not yet submitted
    SUBMITTED = "SUBMITTED"       # Order submitted to broker
    ACCEPTED = "ACCEPTED"         # Order accepted by broker
    FILLED = "FILLED"             # Order fully filled
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # Order partially filled
    CANCELLED = "CANCELLED"       # Order cancelled by user or system
    REJECTED = "REJECTED"         # Order rejected by broker
    EXPIRED = "EXPIRED"           # Order expired (time-based)
    ERROR = "ERROR"               # Order encountered error


class OrderTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class OrderStateMachine:
    """
    Manages order state transitions with validation.
    Ensures orders follow valid state paths.
    """
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        OrderState.PENDING: [OrderState.SUBMITTED, OrderState.CANCELLED, OrderState.REJECTED],
        OrderState.SUBMITTED: [OrderState.ACCEPTED, OrderState.REJECTED, OrderState.EXPIRED, OrderState.CANCELLED],
        OrderState.ACCEPTED: [OrderState.FILLED, OrderState.PARTIALLY_FILLED, OrderState.CANCELLED, OrderState.EXPIRED],
        OrderState.PARTIALLY_FILLED: [OrderState.FILLED, OrderState.CANCELLED, OrderState.EXPIRED],
        OrderState.FILLED: [],  # Terminal state
        OrderState.CANCELLED: [],  # Terminal state
        OrderState.REJECTED: [],  # Terminal state
        OrderState.EXPIRED: [],  # Terminal state
        OrderState.ERROR: [OrderState.PENDING, OrderState.CANCELLED]  # Can retry or cancel
    }
    
    # States that allow modification
    MODIFIABLE_STATES = [OrderState.PENDING, OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED]
    
    # States that allow cancellation
    CANCELLABLE_STATES = [OrderState.PENDING, OrderState.SUBMITTED, OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED]
    
    # Terminal states (no further transitions)
    TERMINAL_STATES = [OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED]
    
    def __init__(self):
        self.current_state = OrderState.PENDING
        self.state_history = []
        self.created_at = dt.now().isoformat()
        self.updated_at = self.created_at
        self.transition_reason = None
    
    def transition_to(self, new_state: OrderState, reason: str = None) -> bool:
        """
        Transition to a new state with validation.
        
        Args:
            new_state: Target state
            reason: Reason for transition (optional)
            
        Returns:
            True if transition successful, False otherwise
            
        Raises:
            OrderTransitionError: If transition is invalid
        """
        # Check if transition is valid
        if new_state not in self.VALID_TRANSITIONS.get(self.current_state, []):
            raise OrderTransitionError(
                f"Invalid state transition: {self.current_state.value} -> {new_state.value}. "
                f"Valid transitions from {self.current_state.value}: "
                f"{[s.value for s in self.VALID_TRANSITIONS[self.current_state]]}"
            )
        
        # Record transition
        self.state_history.append({
            'from_state': self.current_state.value,
            'to_state': new_state.value,
            'timestamp': dt.now().isoformat(),
            'reason': reason or self.transition_reason
        })
        
        # Update state
        self.current_state = new_state
        self.updated_at = dt.now().isoformat()
        self.transition_reason = reason
        
        return True
    
    def can_modify(self) -> bool:
        """Check if order can be modified (SL/TP changes)."""
        return self.current_state in self.MODIFIABLE_STATES
    
    def can_cancel(self) -> bool:
        """Check if order can be cancelled."""
        return self.current_state in self.CANCELLABLE_STATES
    
    def is_terminal(self) -> bool:
        """Check if order is in a terminal state."""
        return self.current_state in self.TERMINAL_STATES
    
    def is_active(self) -> bool:
        """Check if order is still active (not terminal)."""
        return not self.is_terminal()
    
    def get_state_info(self) -> Dict[str, Any]:
        """Get complete state information."""
        return {
            'current_state': self.current_state.value,
            'can_modify': self.can_modify(),
            'can_cancel': self.can_cancel(),
            'is_terminal': self.is_terminal(),
            'is_active': self.is_active(),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'transition_reason': self.transition_reason,
            'state_history': self.state_history
        }


class Order:
    """
    Represents a trading order with state machine integration.
    """
    
    def __init__(self, symbol: str, order_type: str, lot_size: float, 
                 sl: Optional[float] = None, tp: Optional[float] = None,
                 ticket: Optional[str] = None):
        self.symbol = symbol
        self.order_type = order_type.upper()  # BUY or SELL
        self.lot_size = lot_size
        self.sl = sl
        self.tp = tp
        self.ticket = ticket or str(hash(f"{symbol}{order_type}{lot_size}{dt.now()}"))
        
        # State machine
        self.state_machine = OrderStateMachine()
        
        # Order details
        self.submitted_price = None
        self.filled_price = None
        self.filled_quantity = 0.0
        self.filled_time = None
        self.broker_ticket = None  # Actual broker ticket number
        
        # Error tracking
        self.error_message = None
        self.error_code = None
    
    def submit(self, price: float = None) -> bool:
        """Submit order to broker."""
        try:
            self.state_machine.transition_to(OrderState.SUBMITTED, reason="Order submitted to broker")
            self.submitted_price = price
            return True
        except OrderTransitionError as e:
            self.error_message = str(e)
            return False
    
    def accept(self, broker_ticket: str = None) -> bool:
        """Mark order as accepted by broker."""
        try:
            self.state_machine.transition_to(OrderState.ACCEPTED, reason="Order accepted by broker")
            self.broker_ticket = broker_ticket
            return True
        except OrderTransitionError as e:
            self.error_message = str(e)
            return False
    
    def fill(self, price: float, quantity: float = None) -> bool:
        """Mark order as filled."""
        try:
            if quantity and quantity < self.lot_size:
                # Partial fill
                self.state_machine.transition_to(OrderState.PARTIALLY_FILLED, reason="Partial fill")
                self.filled_quantity += quantity
                self.filled_price = price
            else:
                # Full fill
                self.state_machine.transition_to(OrderState.FILLED, reason="Order filled")
                self.filled_quantity = self.lot_size
                self.filled_price = price
                self.filled_time = dt.now().isoformat()
            return True
        except OrderTransitionError as e:
            self.error_message = str(e)
            return False
    
    def cancel(self, reason: str = "USER_CANCELLED") -> bool:
        """Cancel the order."""
        try:
            self.state_machine.transition_to(OrderState.CANCELLED, reason=reason)
            return True
        except OrderTransitionError as e:
            self.error_message = str(e)
            return False
    
    def reject(self, reason: str, error_code: str = None) -> bool:
        """Mark order as rejected."""
        try:
            self.state_machine.transition_to(OrderState.REJECTED, reason=reason)
            self.error_message = reason
            self.error_code = error_code
            return True
        except OrderTransitionError as e:
            self.error_message = str(e)
            return False
    
    def expire(self) -> bool:
        """Mark order as expired."""
        try:
            self.state_machine.transition_to(OrderState.EXPIRED, reason="Order expired")
            return True
        except OrderTransitionError as e:
            self.error_message = str(e)
            return False
    
    def error(self, error_message: str) -> bool:
        """Mark order as having an error."""
        try:
            self.state_machine.transition_to(OrderState.ERROR, reason=error_message)
            self.error_message = error_message
            return True
        except OrderTransitionError as e:
            self.error_message = str(e)
            return False
    
    def modify(self, sl: float = None, tp: float = None) -> bool:
        """Modify SL/TP levels."""
        if not self.state_machine.can_modify():
            self.error_message = f"Cannot modify order in state: {self.state_machine.current_state.value}"
            return False
        
        if sl is not None:
            self.sl = sl
        if tp is not None:
            self.tp = tp
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert order to dictionary for serialization."""
        return {
            'ticket': self.ticket,
            'symbol': self.symbol,
            'order_type': self.order_type,
            'lot_size': self.lot_size,
            'sl': self.sl,
            'tp': self.tp,
            'state': self.state_machine.get_state_info(),
            'submitted_price': self.submitted_price,
            'filled_price': self.filled_price,
            'filled_quantity': self.filled_quantity,
            'filled_time': self.filled_time,
            'broker_ticket': self.broker_ticket,
            'error_message': self.error_message,
            'error_code': self.error_code
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Order':
        """Create order from dictionary."""
        order = cls(
            symbol=data['symbol'],
            order_type=data['order_type'],
            lot_size=data['lot_size'],
            sl=data.get('sl'),
            tp=data.get('tp'),
            ticket=data.get('ticket')
        )
        
        # Restore state
        order.state_machine.current_state = OrderState(data['state']['current_state'])
        order.state_machine.state_history = data['state'].get('state_history', [])
        order.state_machine.created_at = data['state'].get('created_at')
        order.state_machine.updated_at = data['state'].get('updated_at')
        
        # Restore other fields
        order.submitted_price = data.get('submitted_price')
        order.filled_price = data.get('filled_price')
        order.filled_quantity = data.get('filled_quantity', 0.0)
        order.filled_time = data.get('filled_time')
        order.broker_ticket = data.get('broker_ticket')
        order.error_message = data.get('error_message')
        order.error_code = data.get('error_code')
        
        return order


class OrderRegistry:
    """
    Registry for managing all orders with state persistence.
    """
    
    def __init__(self):
        self.orders = {}  # ticket -> Order
    
    def add_order(self, order: Order) -> bool:
        """Add an order to the registry."""
        if order.ticket in self.orders:
            return False
        self.orders[order.ticket] = order
        return True
    
    def get_order(self, ticket: str) -> Optional[Order]:
        """Get an order by ticket."""
        return self.orders.get(ticket)
    
    def remove_order(self, ticket: str) -> bool:
        """Remove an order from the registry."""
        if ticket in self.orders:
            del self.orders[ticket]
            return True
        return False
    
    def get_active_orders(self) -> List[Order]:
        """Get all active (non-terminal) orders."""
        return [order for order in self.orders.values() if order.state_machine.is_active()]
    
    def get_orders_by_symbol(self, symbol: str) -> List[Order]:
        """Get all orders for a specific symbol."""
        return [order for order in self.orders.values() if order.symbol == symbol]
    
    def get_orders_by_state(self, state: OrderState) -> List[Order]:
        """Get all orders in a specific state."""
        return [order for order in self.orders.values() if order.state_machine.current_state == state]
    
    def get_all_orders(self) -> List[Order]:
        """Get all orders."""
        return list(self.orders.values())
    
    def save_to_file(self, filepath: str = "orders.json") -> bool:
        """Save all orders to file."""
        try:
            orders_data = {
                ticket: order.to_dict() 
                for ticket, order in self.orders.items()
            }
            with open(filepath, 'w') as f:
                json.dump(orders_data, f, indent=2)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save orders: {e}")
            return False
    
    def load_from_file(self, filepath: str = "orders.json") -> bool:
        """Load orders from file."""
        try:
            if not os.path.exists(filepath):
                return False
            
            with open(filepath, 'r') as f:
                orders_data = json.load(f)
            
            self.orders = {
                ticket: Order.from_dict(data)
                for ticket, data in orders_data.items()
            }
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load orders: {e}")
            return False


# Global order registry
_order_registry = None

def get_order_registry() -> OrderRegistry:
    """Get the global order registry instance."""
    global _order_registry
    if _order_registry is None:
        _order_registry = OrderRegistry()
    return _order_registry
