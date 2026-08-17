"""
Logging Improvements Module
Provides structured logging with rotation, filtering, and multiple handlers.
"""

import logging
import logging.handlers
from datetime import datetime as dt
from typing import Optional, Dict, Any
import os
import json


class TradingLogger:
    """
    Enhanced logging system for the trading application.
    Provides structured logging with rotation and filtering.
    """
    
    def __init__(self, log_dir: str = "logs", log_level: str = "INFO"):
        """
        Initialize the trading logger.
        
        Args:
            log_dir: Directory for log files
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.log_dir = log_dir
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        
        # Create log directory if it doesn't exist
        os.makedirs(log_dir, exist_ok=True)
        
        # Setup main logger
        self.logger = logging.getLogger("forexscalpper")
        self.logger.setLevel(self.log_level)
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Setup file handlers
        self._setup_file_handlers()
        
        # Setup console handler
        self._setup_console_handler()
        
        # Setup JSON handler for structured logging
        self._setup_json_handler()
        
        # Component-specific loggers
        self.component_loggers = {}
    
    def _setup_file_handlers(self):
        """Setup rotating file handlers for different log levels."""
        # Main log file (all levels)
        main_handler = logging.handlers.RotatingFileHandler(
            os.path.join(self.log_dir, "forexscalpper.log"),
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        main_handler.setLevel(self.log_level)
        main_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        main_handler.setFormatter(main_formatter)
        self.logger.addHandler(main_handler)
        
        # Error log file (ERROR and CRITICAL only)
        error_handler = logging.handlers.RotatingFileHandler(
            os.path.join(self.log_dir, "errors.log"),
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        error_handler.setLevel(logging.ERROR)
        error_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        error_handler.setFormatter(error_formatter)
        self.logger.addHandler(error_handler)
        
        # Trading log file (order execution, positions, etc.)
        trading_handler = logging.handlers.RotatingFileHandler(
            os.path.join(self.log_dir, "trading.log"),
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        trading_handler.setLevel(logging.INFO)
        trading_formatter = logging.Formatter(
            '%(asctime)s - %(message)s'
        )
        trading_handler.setFormatter(trading_formatter)
        self.logger.addHandler(trading_handler)
    
    def _setup_console_handler(self):
        """Setup console handler with colored output."""
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.log_level)
        
        # Simple formatter for console
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
    
    def _setup_json_handler(self):
        """Setup JSON handler for structured logging."""
        json_handler = logging.handlers.RotatingFileHandler(
            os.path.join(self.log_dir, "structured.log"),
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        json_handler.setLevel(self.log_level)
        json_handler.setFormatter(JsonFormatter())
        self.logger.addHandler(json_handler)
    
    def get_component_logger(self, component_name: str) -> logging.Logger:
        """
        Get or create a component-specific logger.
        
        Args:
            component_name: Name of the component (e.g., 'connector', 'risk_controls')
            
        Returns:
            Logger for the component
        """
        if component_name not in self.component_loggers:
            logger = logging.getLogger(f"forexscalpper.{component_name}")
            logger.setLevel(self.log_level)
            self.component_loggers[component_name] = logger
        
        return self.component_loggers[component_name]
    
    def log_order(self, order_type: str, symbol: str, lot_size: float, 
                 price: float, status: str, details: Dict[str, Any] = None):
        """
        Log order execution.
        
        Args:
            order_type: Type of order (BUY/SELL)
            symbol: Trading symbol
            lot_size: Lot size
            price: Order price
            status: Order status
            details: Additional details
        """
        trading_logger = self.get_component_logger("trading")
        message = f"ORDER | {order_type} {symbol} {lot_size} @ {price} | {status}"
        
        if details:
            message += f" | {json.dumps(details)}"
        
        trading_logger.info(message)
    
    def log_position(self, symbol: str, direction: str, lot_size: float,
                    open_price: float, current_price: float, pnl: float):
        """
        Log position update.
        
        Args:
            symbol: Trading symbol
            direction: Position direction (BUY/SELL)
            lot_size: Lot size
            open_price: Open price
            current_price: Current price
            pnl: Current P&L
        """
        trading_logger = self.get_component_logger("trading")
        message = f"POSITION | {symbol} {direction} {lot_size} | Open: {open_price} Current: {current_price} P&L: {pnl:.2f}"
        trading_logger.info(message)
    
    def log_risk_event(self, event_type: str, symbol: str, details: Dict[str, Any]):
        """
        Log risk-related event.
        
        Args:
            event_type: Type of risk event
            symbol: Trading symbol
            details: Event details
        """
        risk_logger = self.get_component_logger("risk")
        message = f"RISK | {event_type} | {symbol} | {json.dumps(details)}"
        risk_logger.warning(message)
    
    def log_system_event(self, event_type: str, status: str, details: Dict[str, Any] = None):
        """
        Log system event.
        
        Args:
            event_type: Type of system event
            status: Event status
            details: Event details
        """
        system_logger = self.get_component_logger("system")
        message = f"SYSTEM | {event_type} | {status}"
        
        if details:
            message += f" | {json.dumps(details)}"
        
        system_logger.info(message)
    
    def log_error(self, component: str, error: Exception, context: Dict[str, Any] = None):
        """
        Log error with context.
        
        Args:
            component: Component where error occurred
            error: Exception object
            context: Additional context
        """
        logger = self.get_component_logger(component)
        message = f"ERROR | {type(error).__name__}: {str(error)}"
        
        if context:
            message += f" | Context: {json.dumps(context)}"
        
        logger.error(message, exc_info=True)
    
    def log_performance(self, metric_name: str, value: float, unit: str = ""):
        """
        Log performance metric.
        
        Args:
            metric_name: Name of metric
            value: Metric value
            unit: Unit of measurement
        """
        perf_logger = self.get_component_logger("performance")
        message = f"PERFORMANCE | {metric_name}: {value}{unit}"
        perf_logger.info(message)
    
    def log_data_event(self, event_type: str, symbol: str, details: Dict[str, Any]):
        """
        Log data-related event.
        
        Args:
            event_type: Type of data event
            symbol: Trading symbol
            details: Event details
        """
        data_logger = self.get_component_logger("data")
        message = f"DATA | {event_type} | {symbol} | {json.dumps(details)}"
        data_logger.info(message)
    
    def set_log_level(self, level: str):
        """
        Change logging level.
        
        Args:
            level: New logging level
        """
        self.log_level = getattr(logging, level.upper(), logging.INFO)
        self.logger.setLevel(self.log_level)
        for handler in self.logger.handlers:
            handler.setLevel(self.log_level)
    
    def get_log_files(self) -> Dict[str, str]:
        """
        Get paths to all log files.
        
        Returns:
            Dictionary mapping log types to file paths
        """
        return {
            'main': os.path.join(self.log_dir, "forexscalpper.log"),
            'errors': os.path.join(self.log_dir, "errors.log"),
            'trading': os.path.join(self.log_dir, "trading.log"),
            'structured': os.path.join(self.log_dir, "structured.log")
        }


class JsonFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as JSON.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: Log record to format
            
        Returns:
            JSON string
        """
        log_data = {
            'timestamp': dt.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


# Global logger instance
_trading_logger = None

def get_trading_logger(log_dir: str = "logs", log_level: str = "INFO") -> TradingLogger:
    """
    Get the global trading logger instance.
    
    Args:
        log_dir: Directory for log files
        log_level: Logging level
        
    Returns:
        TradingLogger instance
    """
    global _trading_logger
    if _trading_logger is None:
        _trading_logger = TradingLogger(log_dir, log_level)
    return _trading_logger


def setup_logging(log_dir: str = "logs", log_level: str = "INFO"):
    """
    Setup logging for the application.
    
    Args:
        log_dir: Directory for log files
        log_level: Logging level
    """
    global _trading_logger
    _trading_logger = TradingLogger(log_dir, log_level)
    return _trading_logger
