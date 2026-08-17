"""
Alerting System Module
Provides alerting capabilities for critical system events.
"""

from datetime import datetime as dt
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
import json


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertType(Enum):
    """Types of alerts."""
    DATA_STALE = "DATA_STALE"
    DATA_QUALITY = "DATA_QUALITY"
    RISK_LIMIT_BREACH = "RISK_LIMIT_BREACH"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    KILL_SWITCH_DEACTIVATED = "KILL_SWITCH_DEACTIVATED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_FAILED = "ORDER_FAILED"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    PERFORMANCE_DEGRADATION = "PERFORMANCE_DEGRADATION"
    POSITION_LIMIT_EXCEEDED = "POSITION_LIMIT_EXCEEDED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    RECONCILIATION_FAILURE = "RECONCILIATION_FAILURE"


class Alert:
    """
    Represents a single alert.
    """
    
    def __init__(self, alert_type: AlertType, severity: AlertSeverity, 
                 message: str, details: Dict[str, Any] = None):
        self.alert_type = alert_type
        self.severity = severity
        self.message = message
        self.details = details or {}
        self.timestamp = dt.now().isoformat()
        self.acknowledged = False
        self.alert_id = f"{alert_type.value}_{self.timestamp}"
    
    def acknowledge(self):
        """Mark alert as acknowledged."""
        self.acknowledged = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary."""
        return {
            'alert_id': self.alert_id,
            'alert_type': self.alert_type.value,
            'severity': self.severity.value,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp,
            'acknowledged': self.acknowledged
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Alert':
        """Create alert from dictionary."""
        alert_type = AlertType(data['alert_type'])
        severity = AlertSeverity(data['severity'])
        
        alert = cls(alert_type, severity, data['message'], data.get('details'))
        alert.timestamp = data['timestamp']
        alert.acknowledged = data.get('acknowledged', False)
        alert.alert_id = data['alert_id']
        
        return alert


class AlertHandler:
    """
    Base class for alert handlers.
    """
    
    def handle_alert(self, alert: Alert) -> bool:
        """
        Handle an alert.
        
        Args:
            alert: The alert to handle
            
        Returns:
            True if handled successfully, False otherwise
        """
        raise NotImplementedError("Subclasses must implement handle_alert")


class ConsoleAlertHandler(AlertHandler):
    """
    Prints alerts to console.
    """
    
    def handle_alert(self, alert: Alert) -> bool:
        """Print alert to console."""
        try:
            timestamp = alert.timestamp
            severity = alert.severity.value
            alert_type = alert.alert_type.value
            message = alert.message
            
            print(f"[{timestamp}] [{severity}] [{alert_type}] {message}")
            
            if alert.details:
                print(f"  Details: {alert.details}")
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to handle alert: {e}")
            return False


class AlertManager:
    """
    Manages alert generation and distribution.
    """
    
    def __init__(self):
        self.alerts = []
        self.alert_handlers = []
        self.alert_history = []
        self.max_history_size = 1000
        
        # Alert thresholds
        self.alert_counts = {alert_type.value: 0 for alert_type in AlertType}
        self.max_alerts_per_type = 10  # Max alerts before rate limiting
        
        # Add default console handler
        self.add_handler(ConsoleAlertHandler())
    
    def add_handler(self, handler: AlertHandler):
        """Add an alert handler."""
        self.alert_handlers.append(handler)
    
    def remove_handler(self, handler: AlertHandler):
        """Remove an alert handler."""
        if handler in self.alert_handlers:
            self.alert_handlers.remove(handler)
    
    def create_alert(self, alert_type: AlertType, severity: AlertSeverity,
                    message: str, details: Dict[str, Any] = None) -> Alert:
        """
        Create and process an alert.
        
        Args:
            alert_type: Type of alert
            severity: Severity level
            message: Alert message
            details: Additional details
            
        Returns:
            Created alert
        """
        alert = Alert(alert_type, severity, message, details)
        
        # Check rate limiting
        alert_type_str = alert_type.value
        if self.alert_counts[alert_type_str] >= self.max_alerts_per_type:
            # Rate limit exceeded, only allow critical alerts
            if severity != AlertSeverity.CRITICAL:
                return alert
        
        # Add to active alerts
        self.alerts.append(alert)
        self.alert_counts[alert_type_str] += 1
        
        # Add to history
        self.alert_history.append(alert.to_dict())
        if len(self.alert_history) > self.max_history_size:
            self.alert_history = self.alert_history[-self.max_history_size:]
        
        # Notify handlers
        for handler in self.alert_handlers:
            try:
                handler.handle_alert(alert)
            except Exception as e:
                print(f"[ERROR] Alert handler failed: {e}")
        
        return alert
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """
        Acknowledge an alert.
        
        Args:
            alert_id: ID of alert to acknowledge
            
        Returns:
            True if acknowledged, False otherwise
        """
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.acknowledge()
                return True
        return False
    
    def get_active_alerts(self) -> List[Alert]:
        """Get list of unacknowledged alerts."""
        return [alert for alert in self.alerts if not alert.acknowledged]
    
    def get_alerts_by_severity(self, severity: AlertSeverity) -> List[Alert]:
        """Get alerts by severity level."""
        return [alert for alert in self.alerts if alert.severity == severity]
    
    def get_alerts_by_type(self, alert_type: AlertType) -> List[Alert]:
        """Get alerts by type."""
        return [alert for alert in self.alerts if alert.alert_type == alert_type]
    
    def get_alert_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get alert history."""
        return self.alert_history[-limit:]
    
    def clear_acknowledged_alerts(self):
        """Remove acknowledged alerts from active list."""
        self.alerts = [alert for alert in self.alerts if not alert.acknowledged]
    
    def reset_alert_counts(self):
        """Reset alert rate limiting counters."""
        self.alert_counts = {alert_type.value: 0 for alert_type in AlertType}
    
    def get_alert_summary(self) -> Dict[str, Any]:
        """
        Get summary of current alert state.
        
        Returns:
            Summary dict
        """
        return {
            'total_alerts': len(self.alert_history),
            'active_alerts': len(self.get_active_alerts()),
            'critical_alerts': len(self.get_alerts_by_severity(AlertSeverity.CRITICAL)),
            'error_alerts': len(self.get_alerts_by_severity(AlertSeverity.ERROR)),
            'warning_alerts': len(self.get_alerts_by_severity(AlertSeverity.WARNING)),
            'by_type': {alert_type.value: len(self.get_alerts_by_type(AlertType(alert_type.value))) 
                        for alert_type in AlertType},
            'timestamp': dt.now().isoformat()
        }
    
    def save_to_file(self, filepath: str = "alerts.json") -> bool:
        """Save alerts to file."""
        try:
            data = {
                'active_alerts': [alert.to_dict() for alert in self.alerts],
                'alert_history': self.alert_history
            }
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save alerts: {e}")
            return False
    
    def load_from_file(self, filepath: str = "alerts.json") -> bool:
        """Load alerts from file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Restore active alerts
            self.alerts = [Alert.from_dict(alert_data) for alert_data in data.get('active_alerts', [])]
            
            # Restore history
            self.alert_history = data.get('alert_history', [])
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load alerts: {e}")
            return False


# Alert convenience functions
def alert_info(message: str, details: Dict[str, Any] = None):
    """Create an INFO alert."""
    manager = get_alert_manager()
    return manager.create_alert(AlertType.SYSTEM_ERROR, AlertSeverity.INFO, message, details)


def alert_warning(message: str, details: Dict[str, Any] = None):
    """Create a WARNING alert."""
    manager = get_alert_manager()
    return manager.create_alert(AlertType.SYSTEM_ERROR, AlertSeverity.WARNING, message, details)


def alert_error(message: str, details: Dict[str, Any] = None):
    """Create an ERROR alert."""
    manager = get_alert_manager()
    return manager.create_alert(AlertType.SYSTEM_ERROR, AlertSeverity.ERROR, message, details)


def alert_critical(message: str, details: Dict[str, Any] = None):
    """Create a CRITICAL alert."""
    manager = get_alert_manager()
    return manager.create_alert(AlertType.SYSTEM_ERROR, AlertSeverity.CRITICAL, message, details)


def alert_data_stale(symbol: str, age_seconds: float):
    """Alert for stale data."""
    manager = get_alert_manager()
    return manager.create_alert(
        AlertType.DATA_STALE,
        AlertSeverity.WARNING,
        f"Stale data detected for {symbol}",
        {'symbol': symbol, 'age_seconds': age_seconds}
    )


def alert_kill_switch_activated(reason: str, triggered_by: str):
    """Alert for kill switch activation."""
    manager = get_alert_manager()
    return manager.create_alert(
        AlertType.KILL_SWITCH_ACTIVATED,
        AlertSeverity.CRITICAL,
        f"Kill switch activated by {triggered_by}",
        {'reason': reason, 'triggered_by': triggered_by}
    )


def alert_risk_limit_breach(limit_type: str, symbol: str, limit_value: float, current_value: float):
    """Alert for risk limit breach."""
    manager = get_alert_manager()
    return manager.create_alert(
        AlertType.RISK_LIMIT_BREACH,
        AlertSeverity.ERROR,
        f"Risk limit breach: {limit_type}",
        {'limit_type': limit_type, 'symbol': symbol, 'limit': limit_value, 'current': current_value}
    )


def alert_order_rejected(order_type: str, symbol: str, reason: str):
    """Alert for order rejection."""
    manager = get_alert_manager()
    return manager.create_alert(
        AlertType.ORDER_REJECTED,
        AlertSeverity.WARNING,
        f"Order rejected: {order_type} {symbol}",
        {'order_type': order_type, 'symbol': symbol, 'reason': reason}
    )


# Global alert manager instance
_alert_manager = None

def get_alert_manager() -> AlertManager:
    """Get the global alert manager instance."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
