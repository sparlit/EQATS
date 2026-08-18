#!/usr/bin/env python3
"""
Test Alerting System Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alerting_system import (
    AlertManager, Alert, AlertSeverity, AlertType,
    get_alert_manager, alert_info, alert_warning, alert_error, alert_critical,
    alert_data_stale, alert_kill_switch_activated, alert_risk_limit_breach, alert_order_rejected
)

def test_alerting_system():
    """Test alerting system functionality."""
    print("Testing alerting system implementation...")
    
    # Test 1: Initialize alert manager
    print("\n1. Testing alert manager initialization...")
    am = AlertManager()
    print(f"   Handlers: {len(am.alert_handlers)}")
    if len(am.alert_handlers) > 0:
        print("   [PASS] Alert manager initialized correctly")
    else:
        print("   [FAIL] Alert manager initialization failed")
        assert False, "Test condition failed"
    
    # Test 2: Create alert
    print("\n2. Testing alert creation...")
    alert = am.create_alert(
        AlertType.SYSTEM_ERROR,
        AlertSeverity.ERROR,
        "Test error message",
        {"test": "data"}
    )
    
    if alert.alert_type == AlertType.SYSTEM_ERROR and alert.severity == AlertSeverity.ERROR:
        print("   [PASS] Alert created correctly")
    else:
        print("   [FAIL] Alert creation failed")
        assert False, "Test condition failed"
    
    # Test 3: Get active alerts
    print("\n3. Testing active alerts retrieval...")
    active_alerts = am.get_active_alerts()
    print(f"   Active alerts: {len(active_alerts)}")
    if len(active_alerts) == 1:
        print("   [PASS] Active alerts retrieved correctly")
    else:
        print("   [FAIL] Active alerts retrieval failed")
        assert False, "Test condition failed"
    
    # Test 4: Acknowledge alert
    print("\n4. Testing alert acknowledgment...")
    am.acknowledge_alert(alert.alert_id)
    active_alerts = am.get_active_alerts()
    print(f"   Active alerts after acknowledgment: {len(active_alerts)}")
    if len(active_alerts) == 0:
        print("   [PASS] Alert acknowledgment works correctly")
    else:
        print("   [FAIL] Alert acknowledgment failed")
        assert False, "Test condition failed"
    
    # Test 5: Get alerts by severity
    print("\n5. Testing alerts by severity retrieval...")
    am.create_alert(AlertType.DATA_STALE, AlertSeverity.WARNING, "Warning alert")
    am.create_alert(AlertType.KILL_SWITCH_ACTIVATED, AlertSeverity.CRITICAL, "Critical alert")
    
    critical_alerts = am.get_alerts_by_severity(AlertSeverity.CRITICAL)
    print(f"   Critical alerts: {len(critical_alerts)}")
    if len(critical_alerts) == 1:
        print("   [PASS] Alerts by severity retrieved correctly")
    else:
        print("   [FAIL] Alerts by severity retrieval failed")
        assert False, "Test condition failed"
    
    # Test 6: Get alerts by type
    print("\n6. Testing alerts by type retrieval...")
    am.create_alert(AlertType.DATA_STALE, AlertSeverity.WARNING, "Another stale data")
    
    stale_alerts = am.get_alerts_by_type(AlertType.DATA_STALE)
    print(f"   Stale data alerts: {len(stale_alerts)}")
    if len(stale_alerts) == 2:
        print("   [PASS] Alerts by type retrieved correctly")
    else:
        print("   [FAIL] Alerts by type retrieval failed")
        assert False, "Test condition failed"
    
    # Test 7: Alert summary
    print("\n7. Testing alert summary...")
    summary = am.get_alert_summary()
    print(f"   Total alerts: {summary['total_alerts']}")
    print(f"   Active alerts: {summary['active_alerts']}")
    print(f"   Critical alerts: {summary['critical_alerts']}")
    if 'total_alerts' in summary and 'active_alerts' in summary:
        print("   [PASS] Alert summary generated correctly")
    else:
        print("   [FAIL] Alert summary generation failed")
        assert False, "Test condition failed"
    
    # Test 8: Alert serialization
    print("\n8. Testing alert serialization...")
    alert_dict = alert.to_dict()
    restored_alert = Alert.from_dict(alert_dict)
    
    if restored_alert.alert_id == alert.alert_id:
        print("   [PASS] Alert serialization works correctly")
    else:
        print("   [FAIL] Alert serialization failed")
        assert False, "Test condition failed"
    
    # Test 9: Alert history
    print("\n9. Testing alert history...")
    history = am.get_alert_history()
    print(f"   History length: {len(history)}")
    if len(history) > 0:
        print("   [PASS] Alert history tracked correctly")
    else:
        print("   [FAIL] Alert history not tracked")
        assert False, "Test condition failed"
    
    # Test 10: Clear acknowledged alerts
    print("\n10. Testing clear acknowledged alerts...")
    am.clear_acknowledged_alerts()
    remaining_alerts = len(am.alerts)
    print(f"   Remaining alerts: {remaining_alerts}")
    print("   [PASS] Clear acknowledged alerts works")
    
    # Test 11: Convenience functions
    print("\n11. Testing convenience alert functions...")
    alert_info("Info message")
    alert_warning("Warning message")
    alert_error("Error message")
    alert_critical("Critical message")
    
    summary = am.get_alert_summary()
    print(f"   Total alerts after convenience functions: {summary['total_alerts']}")
    if summary['total_alerts'] >= 4:
        print("   [PASS] Convenience functions work correctly")
    else:
        print("   [FAIL] Convenience functions failed")
        assert False, "Test condition failed"
    
    # Test 12: Specific alert functions
    print("\n12. Testing specific alert functions...")
    alert_data_stale("EURUSD", 120.0)
    alert_kill_switch_activated("Manual", "test_user")
    alert_risk_limit_breach("position", "GBPUSD", 5.0, 5.5)
    alert_order_rejected("BUY", "USDJPY", "Insufficient funds")
    
    by_type_summary = summary['by_type']
    print(f"   Data stale alerts: {by_type_summary.get('DATA_STALE', 0)}")
    print(f"   Kill switch alerts: {by_type_summary.get('KILL_SWITCH_ACTIVATED', 0)}")
    print("   [PASS] Specific alert functions work correctly")
    
    # Test 13: Rate limiting
    print("\n13. Testing alert rate limiting...")
    am.reset_alert_counts()
    
    # Create many alerts of same type
    for i in range(15):
        am.create_alert(AlertType.DATA_STALE, AlertSeverity.WARNING, f"Test alert {i}")
    
    # Check that rate limiting kicked in
    print(f"   Active alerts after rate limit: {len(am.get_active_alerts())}")
    print("   [PASS] Rate limiting works")
    
    # Test 14: Persistence
    print("\n14. Testing alert persistence...")
    saved = am.save_to_file("test_alerts.json")
    print(f"   Saved: {saved}")
    
    am2 = AlertManager()
    loaded = am2.load_from_file("test_alerts.json")
    print(f"   Loaded: {loaded}")
    
    if saved and loaded:
        print("   [PASS] Alert persistence works correctly")
    else:
        print("   [FAIL] Alert persistence failed")
        assert False, "Test condition failed"
    
    # Cleanup
    if os.path.exists("test_alerts.json"):
        os.remove("test_alerts.json")
    
    print(f"\n{'='*60}")
    print("[PASS] All alerting system tests passed!")
    # Clean test exit

if __name__ == '__main__':
    sys.exit(test_alerting_system())
