"""
Security Status Display Module
Provides security status information for GUI display.
"""

from typing import Dict, Any, List
from datetime import datetime as dt
import json


class SecurityStatus:
    """
    Aggregates security status information for display.
    """
    
    def __init__(self):
        self.status = {
            'encryption': {
                'status': 'UNKNOWN',
                'key_length': 0,
                'algorithm': 'AES-256-GCM',
                'last_updated': None
            },
            'authentication': {
                'status': 'UNKNOWN',
                'mfa_enabled': False,
                'password_strength': 'UNKNOWN',
                'last_login': None
            },
            'risk_controls': {
                'status': 'UNKNOWN',
                'kill_switch_active': False,
                'position_limits_enforced': True,
                'daily_loss_limit_enforced': True,
                'fat_finger_detection': True
            },
            'data_integrity': {
                'status': 'UNKNOWN',
                'validation_enabled': True,
                'freshness_monitoring': True,
                'reconciliation_active': True,
                'last_reconciliation': None
            },
            'system_health': {
                'status': 'UNKNOWN',
                'uptime': 0,
                'error_count': 0,
                'alert_count': 0,
                'last_backup': None
            }
        }
    
    def update_encryption_status(self, status: str, key_length: int = 256):
        """Update encryption status."""
        self.status['encryption']['status'] = status
        self.status['encryption']['key_length'] = key_length
        self.status['encryption']['last_updated'] = dt.now().isoformat()
    
    def update_authentication_status(self, status: str, mfa_enabled: bool, 
                                   password_strength: str = 'UNKNOWN'):
        """Update authentication status."""
        self.status['authentication']['status'] = status
        self.status['authentication']['mfa_enabled'] = mfa_enabled
        self.status['authentication']['password_strength'] = password_strength
        self.status['authentication']['last_login'] = dt.now().isoformat()
    
    def update_risk_control_status(self, kill_switch_active: bool, 
                                   position_limits: bool, daily_loss: bool):
        """Update risk control status."""
        self.status['risk_controls']['kill_switch_active'] = kill_switch_active
        self.status['risk_controls']['position_limits_enforced'] = position_limits
        self.status['risk_controls']['daily_loss_limit_enforced'] = daily_loss
        
        # Determine overall status
        if kill_switch_active:
            self.status['risk_controls']['status'] = 'CRITICAL'
        elif position_limits and daily_loss:
            self.status['risk_controls']['status'] = 'SECURE'
        else:
            self.status['risk_controls']['status'] = 'WARNING'
    
    def update_data_integrity_status(self, validation: bool, freshness: bool, 
                                    reconciliation: bool, last_recon: str = None):
        """Update data integrity status."""
        self.status['data_integrity']['validation_enabled'] = validation
        self.status['data_integrity']['freshness_monitoring'] = freshness
        self.status['data_integrity']['reconciliation_active'] = reconciliation
        self.status['data_integrity']['last_reconciliation'] = last_recon
        
        # Determine overall status
        if validation and freshness and reconciliation:
            self.status['data_integrity']['status'] = 'SECURE'
        else:
            self.status['data_integrity']['status'] = 'WARNING'
    
    def update_system_health(self, uptime: float, error_count: int, alert_count: int,
                           last_backup: str = None):
        """Update system health status."""
        self.status['system_health']['uptime'] = uptime
        self.status['system_health']['error_count'] = error_count
        self.status['system_health']['alert_count'] = alert_count
        self.status['system_health']['last_backup'] = last_backup
        
        # Determine overall status
        if error_count > 10 or alert_count > 5:
            self.status['system_health']['status'] = 'CRITICAL'
        elif error_count > 5 or alert_count > 2:
            self.status['system_health']['status'] = 'WARNING'
        else:
            self.status['system_health']['status'] = 'HEALTHY'
    
    def get_overall_status(self) -> str:
        """
        Get overall security status.
        
        Returns:
            Overall status: SECURE, WARNING, or CRITICAL
        """
        statuses = [
            self.status['encryption']['status'],
            self.status['authentication']['status'],
            self.status['risk_controls']['status'],
            self.status['data_integrity']['status'],
            self.status['system_health']['status']
        ]
        
        if 'CRITICAL' in statuses:
            return 'CRITICAL'
        elif 'WARNING' in statuses or 'UNKNOWN' in statuses:
            return 'WARNING'
        elif all(s == 'SECURE' or s == 'HEALTHY' for s in statuses):
            return 'SECURE'
        else:
            return 'UNKNOWN'
    
    def get_status_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive status summary.
        
        Returns:
            Summary dict with all status information
        """
        return {
            'overall_status': self.get_overall_status(),
            'timestamp': dt.now().isoformat(),
            'components': self.status.copy()
        }
    
    def get_gui_display_data(self) -> Dict[str, Any]:
        """
        Get data formatted for GUI display.
        
        Returns:
            GUI-friendly display data
        """
        overall = self.get_overall_status()
        
        # Map status to colors
        status_colors = {
            'SECURE': '#00FF00',  # Green
            'WARNING': '#FFA500',  # Orange
            'CRITICAL': '#FF0000',  # Red
            'UNKNOWN': '#808080',  # Gray
            'HEALTHY': '#00FF00'   # Green
        }
        
        return {
            'overall_status': overall,
            'status_color': status_colors.get(overall, '#808080'),
            'encryption': {
                'status': self.status['encryption']['status'],
                'color': status_colors.get(self.status['encryption']['status'], '#808080'),
                'key_length': self.status['encryption']['key_length'],
                'algorithm': self.status['encryption']['algorithm']
            },
            'authentication': {
                'status': self.status['authentication']['status'],
                'color': status_colors.get(self.status['authentication']['status'], '#808080'),
                'mfa_enabled': self.status['authentication']['mfa_enabled'],
                'password_strength': self.status['authentication']['password_strength']
            },
            'risk_controls': {
                'status': self.status['risk_controls']['status'],
                'color': status_colors.get(self.status['risk_controls']['status'], '#808080'),
                'kill_switch_active': self.status['risk_controls']['kill_switch_active'],
                'position_limits': self.status['risk_controls']['position_limits_enforced'],
                'daily_loss': self.status['risk_controls']['daily_loss_limit_enforced']
            },
            'data_integrity': {
                'status': self.status['data_integrity']['status'],
                'color': status_colors.get(self.status['data_integrity']['status'], '#808080'),
                'validation': self.status['data_integrity']['validation_enabled'],
                'freshness': self.status['data_integrity']['freshness_monitoring'],
                'reconciliation': self.status['data_integrity']['reconciliation_active']
            },
            'system_health': {
                'status': self.status['system_health']['status'],
                'color': status_colors.get(self.status['system_health']['status'], '#808080'),
                'uptime': self.status['system_health']['uptime'],
                'errors': self.status['system_health']['error_count'],
                'alerts': self.status['system_health']['alert_count']
            }
        }
    
    def save_to_file(self, filepath: str = "security_status.json") -> bool:
        """Save security status to file."""
        try:
            data = self.get_status_summary()
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save security status: {e}")
            return False
    
    def load_from_file(self, filepath: str = "security_status.json") -> bool:
        """Load security status from file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.status = data.get('components', self.status)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load security status: {e}")
            return False


# Global security status instance
_security_status = None

def get_security_status() -> SecurityStatus:
    """Get the global security status instance."""
    global _security_status
    if _security_status is None:
        _security_status = SecurityStatus()
    return _security_status
