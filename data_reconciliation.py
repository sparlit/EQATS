"""
Data Reconciliation Module
Reconciles local data with broker data to detect discrepancies.
"""

from datetime import datetime as dt
from typing import Dict, Any, Optional, List
import json


class ReconciliationResult:
    """Result of a reconciliation operation."""
    
    def __init__(self):
        self.success = True
        self.discrepancies = []
        self.timestamp = dt.now().isoformat()
        self.summary = {
            'total_checks': 0,
            'passed_checks': 0,
            'failed_checks': 0
        }
    
    def add_discrepancy(self, check_type: str, expected: Any, actual: Any, 
                       severity: str = "ERROR", details: str = None):
        """Add a discrepancy to the result."""
        self.discrepancies.append({
            'check_type': check_type,
            'expected': expected,
            'actual': actual,
            'severity': severity,
            'details': details,
            'timestamp': dt.now().isoformat()
        })
        self.summary['failed_checks'] += 1
    
    def add_passed_check(self):
        """Increment passed checks counter."""
        self.summary['passed_checks'] += 1
    
    def add_total_check(self):
        """Increment total checks counter."""
        self.summary['total_checks'] += 1
    
    def has_discrepancies(self) -> bool:
        """Check if there are any discrepancies."""
        return len(self.discrepancies) > 0
    
    def has_critical_discrepancies(self) -> bool:
        """Check if there are any critical discrepancies."""
        return any(d['severity'] == 'CRITICAL' for d in self.discrepancies)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            'success': self.success,
            'discrepancies': self.discrepancies,
            'timestamp': self.timestamp,
            'summary': self.summary
        }


class DataReconciler:
    """
    Reconciles local data with broker data.
    Detects discrepancies in trades, orders, balances, and positions.
    """
    
    def __init__(self):
        self.reconciliation_history = []
        self.tolerance_pounds = 0.01  # Tolerance for balance reconciliation
        self.tolerance_lots = 0.001  # Tolerance for position reconciliation
    
    def reconcile_balance(self, local_balance: float, broker_balance: float, 
                         currency: str = "USD") -> ReconciliationResult:
        """
        Reconcile local balance with broker balance.
        
        Args:
            local_balance: Local balance value
            broker_balance: Broker balance value
            currency: Currency code
            
        Returns:
            Reconciliation result
        """
        result = ReconciliationResult()
        result.add_total_check()
        
        difference = abs(local_balance - broker_balance)
        
        if difference <= self.tolerance_pounds:
            result.add_passed_check()
        else:
            severity = "WARNING" if difference < 10.0 else "CRITICAL"
            result.add_discrepancy(
                check_type="BALANCE",
                expected=local_balance,
                actual=broker_balance,
                severity=severity,
                details=f"Balance discrepancy of {difference:.2f} {currency}"
            )
            if severity == "CRITICAL":
                result.success = False
        
        return result
    
    def reconcile_positions(self, local_positions: List[Dict], 
                          broker_positions: List[Dict]) -> ReconciliationResult:
        """
        Reconcile local positions with broker positions.
        
        Args:
            local_positions: List of local position dicts
            broker_positions: List of broker position dicts
            
        Returns:
            Reconciliation result
        """
        result = ReconciliationResult()
        
        # Create lookup by symbol
        local_by_symbol = {p['symbol']: p for p in local_positions}
        broker_by_symbol = {p['symbol']: p for p in broker_positions}
        
        all_symbols = set(local_by_symbol.keys()) | set(broker_by_symbol.keys())
        
        for symbol in all_symbols:
            result.add_total_check()
            
            local_pos = local_by_symbol.get(symbol)
            broker_pos = broker_by_symbol.get(symbol)
            
            # Both have position
            if local_pos and broker_pos:
                local_lots = local_pos.get('lot_size', 0)
                broker_lots = broker_pos.get('lot_size', 0)
                
                if abs(local_lots - broker_lots) <= self.tolerance_lots:
                    result.add_passed_check()
                else:
                    severity = "WARNING" if abs(local_lots - broker_lots) < 1.0 else "CRITICAL"
                    result.add_discrepancy(
                        check_type="POSITION_SIZE",
                        expected=local_lots,
                        actual=broker_lots,
                        severity=severity,
                        details=f"Position size mismatch for {symbol}"
                    )
                    if severity == "CRITICAL":
                        result.success = False
            
            # Only local has position
            elif local_pos and not broker_pos:
                result.add_discrepancy(
                    check_type="MISSING_BROKER_POSITION",
                    expected=local_pos,
                    actual=None,
                    severity="CRITICAL",
                    details=f"Local position {symbol} not found in broker"
                )
                result.success = False
            
            # Only broker has position
            elif broker_pos and not local_pos:
                result.add_discrepancy(
                    check_type="ORPHAN_BROKER_POSITION",
                    expected=None,
                    actual=broker_pos,
                    severity="CRITICAL",
                    details=f"Broker position {symbol} not found locally"
                )
                result.success = False
        
        return result
    
    def reconcile_orders(self, local_orders: List[Dict], 
                       broker_orders: List[Dict]) -> ReconciliationResult:
        """
        Reconcile local orders with broker orders.
        
        Args:
            local_orders: List of local order dicts
            broker_orders: List of broker order dicts
            
        Returns:
            Reconciliation result
        """
        result = ReconciliationResult()
        
        # Create lookup by ticket
        local_by_ticket = {o['ticket']: o for o in local_orders}
        broker_by_ticket = {o['ticket']: o for o in broker_orders}
        
        all_tickets = set(local_by_ticket.keys()) | set(broker_by_ticket.keys())
        
        for ticket in all_tickets:
            result.add_total_check()
            
            local_order = local_by_ticket.get(ticket)
            broker_order = broker_by_ticket.get(ticket)
            
            # Both have order
            if local_order and broker_order:
                local_state = local_order.get('state')
                broker_state = broker_order.get('state')
                
                if local_state == broker_state:
                    result.add_passed_check()
                else:
                    result.add_discrepancy(
                        check_type="ORDER_STATE",
                        expected=local_state,
                        actual=broker_state,
                        severity="WARNING",
                        details=f"Order state mismatch for ticket {ticket}"
                    )
            
            # Only local has order
            elif local_order and not broker_order:
                local_state = local_order.get('state')
                # If order is terminal, it's okay if not in broker
                if local_state in ['FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED']:
                    result.add_passed_check()
                else:
                    result.add_discrepancy(
                        check_type="MISSING_BROKER_ORDER",
                        expected=local_order,
                        actual=None,
                        severity="WARNING",
                        details=f"Local order {ticket} not found in broker"
                    )
            
            # Only broker has order
            elif broker_order and not local_order:
                result.add_discrepancy(
                    check_type="ORPHAN_BROKER_ORDER",
                    expected=None,
                    actual=broker_order,
                    severity="WARNING",
                    details=f"Broker order {ticket} not found locally"
                )
        
        return result
    
    def reconcile_trades(self, local_trades: List[Dict], 
                       broker_trades: List[Dict]) -> ReconciliationResult:
        """
        Reconcile local trades with broker trades.
        
        Args:
            local_trades: List of local trade dicts
            broker_trades: List of broker trade dicts
            
        Returns:
            Reconciliation result
        """
        result = ReconciliationResult()
        
        # Create lookup by trade ID
        local_by_id = {t['trade_id']: t for t in local_trades}
        broker_by_id = {t['trade_id']: t for t in broker_trades}
        
        all_ids = set(local_by_id.keys()) | set(broker_by_id.keys())
        
        for trade_id in all_ids:
            result.add_total_check()
            
            local_trade = local_by_id.get(trade_id)
            broker_trade = broker_by_id.get(trade_id)
            
            # Both have trade
            if local_trade and broker_trade:
                local_price = local_trade.get('price')
                broker_price = broker_trade.get('price')
                
                if abs(local_price - broker_price) < 0.0001:  # Small tolerance
                    result.add_passed_check()
                else:
                    result.add_discrepancy(
                        check_type="TRADE_PRICE",
                        expected=local_price,
                        actual=broker_price,
                        severity="WARNING",
                        details=f"Trade price mismatch for trade {trade_id}"
                    )
            
            # Only local has trade
            elif local_trade and not broker_trade:
                result.add_discrepancy(
                    check_type="MISSING_BROKER_TRADE",
                    expected=local_trade,
                    actual=None,
                    severity="WARNING",
                    details=f"Local trade {trade_id} not found in broker"
                )
            
            # Only broker has trade
            elif broker_trade and not local_trade:
                result.add_discrepancy(
                    check_type="ORPHAN_BROKER_TRADE",
                    expected=None,
                    actual=broker_trade,
                    severity="WARNING",
                    details=f"Broker trade {trade_id} not found locally"
                )
        
        return result
    
    def full_reconciliation(self, local_data: Dict[str, Any], 
                          broker_data: Dict[str, Any]) -> ReconciliationResult:
        """
        Perform full reconciliation of all data types.
        
        Args:
            local_data: Dict containing local data (balance, positions, orders, trades)
            broker_data: Dict containing broker data (balance, positions, orders, trades)
            
        Returns:
            Comprehensive reconciliation result
        """
        result = ReconciliationResult()
        
        # Reconcile balance
        balance_result = self.reconcile_balance(
            local_data.get('balance', 0),
            broker_data.get('balance', 0),
            local_data.get('currency', 'USD')
        )
        result.discrepancies.extend(balance_result.discrepancies)
        result.summary['total_checks'] += balance_result.summary['total_checks']
        result.summary['passed_checks'] += balance_result.summary['passed_checks']
        result.summary['failed_checks'] += balance_result.summary['failed_checks']
        
        # Reconcile positions
        pos_result = self.reconcile_positions(
            local_data.get('positions', []),
            broker_data.get('positions', [])
        )
        result.discrepancies.extend(pos_result.discrepancies)
        result.summary['total_checks'] += pos_result.summary['total_checks']
        result.summary['passed_checks'] += pos_result.summary['passed_checks']
        result.summary['failed_checks'] += pos_result.summary['failed_checks']
        
        # Reconcile orders
        order_result = self.reconcile_orders(
            local_data.get('orders', []),
            broker_data.get('orders', [])
        )
        result.discrepancies.extend(order_result.discrepancies)
        result.summary['total_checks'] += order_result.summary['total_checks']
        result.summary['passed_checks'] += order_result.summary['passed_checks']
        result.summary['failed_checks'] += order_result.summary['failed_checks']
        
        # Reconcile trades
        trade_result = self.reconcile_trades(
            local_data.get('trades', []),
            broker_data.get('trades', [])
        )
        result.discrepancies.extend(trade_result.discrepancies)
        result.summary['total_checks'] += trade_result.summary['total_checks']
        result.summary['passed_checks'] += trade_result.summary['passed_checks']
        result.summary['failed_checks'] += trade_result.summary['failed_checks']
        
        # Determine overall success
        result.success = not result.has_critical_discrepancies()
        
        # Store in history
        self.reconciliation_history.append({
            'timestamp': dt.now().isoformat(),
            'result': result.to_dict()
        })
        
        return result
    
    def get_reconciliation_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent reconciliation history."""
        return self.reconciliation_history[-limit:]
    
    def should_block_trading(self) -> bool:
        """
        Determine if trading should be blocked due to reconciliation failures.
        
        Returns:
            True if trading should be blocked, False otherwise
        """
        if not self.reconciliation_history:
            return False
        
        # Check the most recent reconciliation
        latest = self.reconciliation_history[-1]
        result = latest['result']
        
        return result['success'] == False or result['summary']['failed_checks'] > 0


# Global reconciler instance
_data_reconciler = None

def get_data_reconciler() -> DataReconciler:
    """Get the global data reconciler instance."""
    global _data_reconciler
    if _data_reconciler is None:
        _data_reconciler = DataReconciler()
    return _data_reconciler
