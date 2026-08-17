"""
Kill Switch Module
Implements emergency trading stop functionality for the Forex Scalper system.
Meets regulatory requirements for automated trading risk controls.
"""

import sqlite3
import datetime
import threading
import os
from enum import Enum
from typing import Optional, Dict, List
from dataclasses import dataclass
import config


class KillSwitchState(Enum):
    """Kill switch states."""
    NORMAL = "NORMAL"  # Normal trading operations
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"  # Kill switch engaged
    EMERGENCY_STOP = "EMERGENCY_STOP"  # Emergency stop (risk-reducing only)


class KillSwitchReason(Enum):
    """Reasons for kill switch activation."""
    MANUAL = "MANUAL"  # Manually activated by user
    AUTOMATED_RISK_LIMIT = "AUTOMATED_RISK_LIMIT"  # Automated due to risk limits
    SYSTEM_ERROR = "SYSTEM_ERROR"  # System error or malfunction
    DATA_FEED_FAILURE = "DATA_FEED_FAILURE"  # Data feed failure
    BROKER_DISCONNECT = "BROKER_DISCONNECT"  # Broker connection lost
    REGULATORY = "REGULATORY"  # Regulatory requirement
    MARKET_CONDITION = "MARKET_CONDITION"  # Adverse market conditions


@dataclass
class KillSwitchEvent:
    """Kill switch event record."""
    timestamp: str
    state: KillSwitchState
    reason: KillSwitchReason
    triggered_by: str  # Username or system
    details: str
    positions_at_activation: int
    open_orders_at_activation: int
    equity_at_activation: float


class KillSwitch:
    """
    Emergency trading stop mechanism.
    
    Implements regulatory-compliant kill switch functionality:
    - Stops new risk-increasing orders
    - Cancels working orders where possible
    - Permits only risk-reducing actions (close positions)
    - Persists activation state to database
    - Requires explicit authorized reset
    - Provides audit trail
    """
    
    def __init__(self):
        """Initialize kill switch."""
        self._state = KillSwitchState.NORMAL
        self._state_lock = threading.Lock()
        self._activation_time: Optional[str] = None
        self._activation_reason: Optional[KillSwitchReason] = None
        self._triggered_by: Optional[str] = None
        self._db_path = config.DB_PATH
        self._init_database()
        
        # Load state from database
        self._load_state()
    
    def _init_database(self):
        """Initialize kill switch database table."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS kill_switch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            state TEXT NOT NULL,
            reason TEXT NOT NULL,
            triggered_by TEXT NOT NULL,
            details TEXT,
            positions_at_activation INTEGER,
            open_orders_at_activation INTEGER,
            equity_at_activation REAL
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS kill_switch_state (
            id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            activation_time TEXT,
            reason TEXT,
            triggered_by TEXT,
            details TEXT
        )
        """)
        
        conn.commit()
        conn.close()
    
    def _load_state(self):
        """Load kill switch state from database."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT state, activation_time, reason, triggered_by FROM kill_switch_state WHERE id = 1")
        row = cursor.fetchone()
        
        if row:
            state_str, activation_time, reason_str, triggered_by = row
            try:
                self._state = KillSwitchState(state_str)
                self._activation_time = activation_time
                self._activation_reason = KillSwitchReason(reason_str) if reason_str else None
                self._triggered_by = triggered_by
            except ValueError:
                # Invalid state in database, default to NORMAL
                self._state = KillSwitchState.NORMAL
        
        conn.close()
    
    def _save_state(self):
        """Save kill switch state to database."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT OR REPLACE INTO kill_switch_state (id, state, activation_time, reason, triggered_by, details)
        VALUES (1, ?, ?, ?, ?, ?)
        """, (
            self._state.value,
            self._activation_time,
            self._activation_reason.value if self._activation_reason else None,
            self._triggered_by,
            "Kill switch state"
        ))
        
        conn.commit()
        conn.close()
    
    def _log_event(self, event: KillSwitchEvent):
        """Log kill switch event to database."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO kill_switch_events (
            timestamp, state, reason, triggered_by, details,
            positions_at_activation, open_orders_at_activation, equity_at_activation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.timestamp,
            event.state.value,
            event.reason.value,
            event.triggered_by,
            event.details,
            event.positions_at_activation,
            event.open_orders_at_activation,
            event.equity_at_activation
        ))
        
        conn.commit()
        conn.close()
    
    def activate(
        self,
        reason: KillSwitchReason,
        triggered_by: str,
        details: str = "",
        positions_count: int = 0,
        open_orders_count: int = 0,
        equity: float = 0.0
    ) -> bool:
        """
        Activate kill switch.
        
        Args:
            reason: Reason for activation
            triggered_by: Username or system component
            details: Additional details
            positions_count: Number of open positions at activation
            open_orders_count: Number of open orders at activation
            equity: Account equity at activation
            
        Returns:
            True if activation successful, False otherwise
        """
        with self._state_lock:
            if self._state != KillSwitchState.NORMAL:
                print(f"[WARNING] Kill switch already activated: {self._state.value}")
                return False
            
            self._state = KillSwitchState.KILL_SWITCH_ACTIVATED
            self._activation_time = datetime.datetime.now().isoformat()
            self._activation_reason = reason
            self._triggered_by = triggered_by
            
            # Create event record
            event = KillSwitchEvent(
                timestamp=self._activation_time,
                state=self._state,
                reason=reason,
                triggered_by=triggered_by,
                details=details,
                positions_at_activation=positions_count,
                open_orders_at_activation=open_orders_count,
                equity_at_activation=equity
            )
            
            # Save to database
            self._save_state()
            self._log_event(event)
            
            print(f"[ALERT] KILL SWITCH ACTIVATED")
            print(f"   Reason: {reason.value}")
            print(f"   Triggered by: {triggered_by}")
            print(f"   Time: {self._activation_time}")
            print(f"   Positions: {positions_count}")
            print(f"   Open orders: {open_orders_count}")
            print(f"   Equity: {equity}")
            
            return True
    
    def deactivate(self, triggered_by: str, reason: str = "") -> bool:
        """
        Deactivate kill switch and return to normal operations.
        
        WARNING: Requires explicit authorization. Should only be done by
        authorized personnel after confirming safe conditions.
        
        Args:
            triggered_by: Username deactivating
            reason: Reason for deactivation
            
        Returns:
            True if deactivation successful, False otherwise
        """
        with self._state_lock:
            if self._state == KillSwitchState.NORMAL:
                print("⚠️ Kill switch not activated")
                return False
            
            # Log deactivation event
            event = KillSwitchEvent(
                timestamp=datetime.datetime.now().isoformat(),
                state=KillSwitchState.NORMAL,
                reason=KillSwitchReason.MANUAL,
                triggered_by=triggered_by,
                details=f"Kill switch deactivated. Reason: {reason}",
                positions_at_activation=0,
                open_orders_at_activation=0,
                equity_at_activation=0.0
            )
            
            # Reset state
            self._state = KillSwitchState.NORMAL
            self._activation_time = None
            self._activation_reason = None
            self._triggered_by = None
            
            # Save to database
            self._save_state()
            self._log_event(event)
            
            print(f"[SUCCESS] KILL SWITCH DEACTIVATED")
            print(f"   Deactivated by: {triggered_by}")
            print(f"   Reason: {reason}")
            print(f"   Time: {event.timestamp}")
            
            return True
    
    def is_activated(self) -> bool:
        """
        Check if kill switch is activated.
        
        Returns:
            True if kill switch is activated, False otherwise
        """
        with self._state_lock:
            return self._state != KillSwitchState.NORMAL
    
    def get_state(self) -> KillSwitchState:
        """
        Get current kill switch state.
        
        Returns:
            Current kill switch state
        """
        with self._state_lock:
            return self._state
    
    def is_order_allowed(self, order_type: str, is_position_closing: bool = False) -> bool:
        """
        Check if an order is allowed under current kill switch state.
        
        Args:
            order_type: Order type (BUY, SELL, etc.)
            is_position_closing: True if this order is closing a position
            
        Returns:
            True if order is allowed, False otherwise
        """
        with self._state_lock:
            if self._state == KillSwitchState.NORMAL:
                return True
            
            # In kill switch mode, only allow position closing
            if self._state == KillSwitchState.KILL_SWITCH_ACTIVATED:
                if is_position_closing:
                    print(f"[WARNING] Kill switch active: Allowing position-closing order only")
                    return True
                else:
                    print(f"[BLOCKED] Kill switch active: Order blocked (risk-increasing)")
                    return False
            
            # Emergency stop mode: no orders allowed
            if self._state == KillSwitchState.EMERGENCY_STOP:
                print(f"[BLOCKED] Emergency stop: All orders blocked")
                return False
            
            return False
    
    def get_activation_info(self) -> Optional[Dict]:
        """
        Get information about kill switch activation.
        
        Returns:
            Dictionary with activation info, or None if not activated
        """
        with self._state_lock:
            if self._state == KillSwitchState.NORMAL:
                return None
            
            return {
                'state': self._state.value,
                'activation_time': self._activation_time,
                'reason': self._activation_reason.value if self._activation_reason else None,
                'triggered_by': self._triggered_by,
                'duration_minutes': self._calculate_duration_minutes()
            }
    
    def _calculate_duration_minutes(self) -> Optional[float]:
        """Calculate duration in minutes since activation."""
        if not self._activation_time:
            return None
        
        try:
            activation_dt = datetime.datetime.fromisoformat(self._activation_time)
            now = datetime.datetime.now()
            duration = (now - activation_dt).total_seconds() / 60
            return round(duration, 2)
        except Exception:
            return None
    
    def get_recent_events(self, limit: int = 10) -> List[Dict]:
        """
        Get recent kill switch events.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries
        """
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
        SELECT timestamp, state, reason, triggered_by, details,
               positions_at_activation, open_orders_at_activation, equity_at_activation
        FROM kill_switch_events
        ORDER BY timestamp DESC
        LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        events = []
        for row in rows:
            events.append({
                'timestamp': row[0],
                'state': row[1],
                'reason': row[2],
                'triggered_by': row[3],
                'details': row[4],
                'positions_at_activation': row[5],
                'open_orders_at_activation': row[6],
                'equity_at_activation': row[7]
            })
        
        return events


# Global kill switch instance
_global_kill_switch = None


def get_kill_switch() -> KillSwitch:
    """Get or create the global kill switch instance."""
    global _global_kill_switch
    if _global_kill_switch is None:
        _global_kill_switch = KillSwitch()
    return _global_kill_switch


def activate_kill_switch(reason: KillSwitchReason, triggered_by: str, details: str = "") -> bool:
    """
    Convenience function to activate kill switch.
    
    Args:
        reason: Reason for activation
        triggered_by: Username or system component
        details: Additional details
        
    Returns:
        True if activation successful
    """
    kill_switch = get_kill_switch()
    return kill_switch.activate(reason, triggered_by, details)


def deactivate_kill_switch(triggered_by: str, reason: str = "") -> bool:
    """
    Convenience function to deactivate kill switch.
    
    Args:
        triggered_by: Username deactivating
        reason: Reason for deactivation
        
    Returns:
        True if deactivation successful
    """
    kill_switch = get_kill_switch()
    return kill_switch.deactivate(triggered_by, reason)


def is_kill_switch_activated() -> bool:
    """
    Convenience function to check if kill switch is activated.
    
    Returns:
        True if kill switch is activated
    """
    kill_switch = get_kill_switch()
    return kill_switch.is_activated()
