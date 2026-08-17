"""
Validation Feedback to GUI Module
Provides validation feedback information for GUI display.
"""

from typing import Dict, Any, List
from datetime import datetime as dt
import json


class ValidationFeedback:
    """
    Aggregates validation feedback information for GUI display.
    """
    
    def __init__(self):
        self.feedback = {
            'order_validation': {
                'last_check': None,
                'status': 'UNKNOWN',
                'errors': [],
                'warnings': [],
                'last_order': {}
            },
            'position_validation': {
                'last_check': None,
                'status': 'UNKNOWN',
                'errors': [],
                'warnings': [],
                'position_count': 0
            },
            'data_validation': {
                'last_check': None,
                'status': 'UNKNOWN',
                'errors': [],
                'warnings': [],
                'quality_score': 0.0,
                'symbols_validated': []
            },
            'risk_validation': {
                'last_check': None,
                'status': 'UNKNOWN',
                'errors': [],
                'warnings': [],
                'limits_active': True
            }
        }
    
    def add_order_validation(self, valid: bool, order: Dict[str, Any], 
                           errors: List[str] = None, warnings: List[str] = None):
        """
        Add order validation feedback.
        
        Args:
            valid: Whether the order is valid
            order: Order details
            errors: List of errors
            warnings: List of warnings
        """
        self.feedback['order_validation']['last_check'] = dt.now().isoformat()
        self.feedback['order_validation']['status'] = 'VALID' if valid else 'INVALID'
        self.feedback['order_validation']['errors'] = errors or []
        self.feedback['order_validation']['warnings'] = warnings or []
        self.feedback['order_validation']['last_order'] = order
    
    def add_position_validation(self, valid: bool, position_count: int,
                                errors: List[str] = None, warnings: List[str] = None):
        """
        Add position validation feedback.
        
        Args:
            valid: Whether positions are valid
            position_count: Number of positions
            errors: List of errors
            warnings: List of warnings
        """
        self.feedback['position_validation']['last_check'] = dt.now().isoformat()
        self.feedback['position_validation']['status'] = 'VALID' if valid else 'INVALID'
        self.feedback['position_validation']['errors'] = errors or []
        self.feedback['position_validation']['warnings'] = warnings or []
        self.feedback['position_validation']['position_count'] = position_count
    
    def add_data_validation(self, valid: bool, quality_score: float, 
                           symbols: List[str], errors: List[str] = None, 
                           warnings: List[str] = None):
        """
        Add data validation feedback.
        
        Args:
            valid: Whether data is valid
            quality_score: Data quality score (0-100)
            symbols: List of validated symbols
            errors: List of errors
            warnings: List of warnings
        """
        self.feedback['data_validation']['last_check'] = dt.now().isoformat()
        self.feedback['data_validation']['status'] = 'VALID' if valid else 'INVALID'
        self.feedback['data_validation']['errors'] = errors or []
        self.feedback['data_validation']['warnings'] = warnings or []
        self.feedback['data_validation']['quality_score'] = quality_score
        self.feedback['data_validation']['symbols_validated'] = symbols
    
    def add_risk_validation(self, valid: bool, limits_active: bool,
                           errors: List[str] = None, warnings: List[str] = None):
        """
        Add risk validation feedback.
        
        Args:
            valid: Whether risk checks pass
            limits_active: Whether limits are active
            errors: List of errors
            warnings: List of warnings
        """
        self.feedback['risk_validation']['last_check'] = dt.now().isoformat()
        self.feedback['risk_validation']['status'] = 'VALID' if valid else 'INVALID'
        self.feedback['risk_validation']['errors'] = errors or []
        self.feedback['risk_validation']['warnings'] = warnings or []
        self.feedback['risk_validation']['limits_active'] = limits_active
    
    def get_overall_status(self) -> str:
        """
        Get overall validation status.
        
        Returns:
            Overall status: VALID, WARNING, or INVALID
        """
        statuses = [
            self.feedback['order_validation']['status'],
            self.feedback['position_validation']['status'],
            self.feedback['data_validation']['status'],
            self.feedback['risk_validation']['status']
        ]
        
        if 'INVALID' in statuses:
            return 'INVALID'
        elif 'WARNING' in statuses or 'UNKNOWN' in statuses:
            return 'WARNING'
        elif all(s == 'VALID' for s in statuses):
            return 'VALID'
        else:
            return 'UNKNOWN'
    
    def get_feedback_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive feedback summary.
        
        Returns:
            Summary dict with all feedback information
        """
        return {
            'overall_status': self.get_overall_status(),
            'timestamp': dt.now().isoformat(),
            'components': self.feedback.copy()
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
            'VALID': '#00FF00',  # Green
            'WARNING': '#FFA500',  # Orange
            'INVALID': '#FF0000',  # Red
            'UNKNOWN': '#808080'   # Gray
        }
        
        return {
            'overall_status': overall,
            'status_color': status_colors.get(overall, '#808080'),
            'order_validation': {
                'status': self.feedback['order_validation']['status'],
                'color': status_colors.get(self.feedback['order_validation']['status'], '#808080'),
                'errors': self.feedback['order_validation']['errors'],
                'warnings': self.feedback['order_validation']['warnings'],
                'last_order': self.feedback['order_validation']['last_order']
            },
            'position_validation': {
                'status': self.feedback['position_validation']['status'],
                'color': status_colors.get(self.feedback['position_validation']['status'], '#808080'),
                'errors': self.feedback['position_validation']['errors'],
                'warnings': self.feedback['position_validation']['warnings'],
                'position_count': self.feedback['position_validation']['position_count']
            },
            'data_validation': {
                'status': self.feedback['data_validation']['status'],
                'color': status_colors.get(self.feedback['data_validation']['status'], '#808080'),
                'errors': self.feedback['data_validation']['errors'],
                'warnings': self.feedback['data_validation']['warnings'],
                'quality_score': self.feedback['data_validation']['quality_score'],
                'symbols': self.feedback['data_validation']['symbols_validated']
            },
            'risk_validation': {
                'status': self.feedback['risk_validation']['status'],
                'color': status_colors.get(self.feedback['risk_validation']['status'], '#808080'),
                'errors': self.feedback['risk_validation']['errors'],
                'warnings': self.feedback['risk_validation']['warnings'],
                'limits_active': self.feedback['risk_validation']['limits_active']
            }
        }
    
    def get_error_count(self) -> int:
        """Get total number of errors across all validations."""
        total = 0
        for component in self.feedback.values():
            total += len(component.get('errors', []))
        return total
    
    def get_warning_count(self) -> int:
        """Get total number of warnings across all validations."""
        total = 0
        for component in self.feedback.values():
            total += len(component.get('warnings', []))
        return total
    
    def clear_feedback(self):
        """Clear all validation feedback."""
        self.__init__()
    
    def save_to_file(self, filepath: str = "validation_feedback.json") -> bool:
        """Save validation feedback to file."""
        try:
            data = self.get_feedback_summary()
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save validation feedback: {e}")
            return False
    
    def load_from_file(self, filepath: str = "validation_feedback.json") -> bool:
        """Load validation feedback from file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.feedback = data.get('components', self.feedback)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to load validation feedback: {e}")
            return False


# Global validation feedback instance
_validation_feedback = None

def get_validation_feedback() -> ValidationFeedback:
    """Get the global validation feedback instance."""
    global _validation_feedback
    if _validation_feedback is None:
        _validation_feedback = ValidationFeedback()
    return _validation_feedback
