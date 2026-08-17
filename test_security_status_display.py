#!/usr/bin/env python3
"""
Test Security Status Display Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from security_status_display import SecurityStatus, get_security_status

def test_security_status_display():
    """Test security status display functionality."""
    print("Testing security status display implementation...")
    
    # Test 1: Initialize security status
    print("\n1. Testing security status initialization...")
    ss = SecurityStatus()
    print(f"   Status keys: {list(ss.status.keys())}")
    if len(ss.status) == 5:
        print("   [PASS] Security status initialized correctly")
    else:
        print("   [FAIL] Security status initialization failed")
        return 1
    
    # Test 2: Update encryption status
    print("\n2. Testing encryption status update...")
    ss.update_encryption_status('SECURE', key_length=256)
    print(f"   Encryption status: {ss.status['encryption']['status']}")
    print(f"   Key length: {ss.status['encryption']['key_length']}")
    if ss.status['encryption']['status'] == 'SECURE':
        print("   [PASS] Encryption status updated correctly")
    else:
        print("   [FAIL] Encryption status update failed")
        return 1
    
    # Test 3: Update authentication status
    print("\n3. Testing authentication status update...")
    ss.update_authentication_status('SECURE', mfa_enabled=True, password_strength='STRONG')
    print(f"   Authentication status: {ss.status['authentication']['status']}")
    print(f"   MFA enabled: {ss.status['authentication']['mfa_enabled']}")
    if ss.status['authentication']['mfa_enabled']:
        print("   [PASS] Authentication status updated correctly")
    else:
        print("   [FAIL] Authentication status update failed")
        return 1
    
    # Test 4: Update risk control status
    print("\n4. Testing risk control status update...")
    ss.update_risk_control_status(kill_switch_active=False, position_limits=True, daily_loss=True)
    print(f"   Risk control status: {ss.status['risk_controls']['status']}")
    print(f"   Kill switch active: {ss.status['risk_controls']['kill_switch_active']}")
    if ss.status['risk_controls']['status'] == 'SECURE':
        print("   [PASS] Risk control status updated correctly")
    else:
        print("   [FAIL] Risk control status update failed")
        return 1
    
    # Test 5: Update data integrity status
    print("\n5. Testing data integrity status update...")
    ss.update_data_integrity_status(validation=True, freshness=True, reconciliation=True)
    print(f"   Data integrity status: {ss.status['data_integrity']['status']}")
    if ss.status['data_integrity']['status'] == 'SECURE':
        print("   [PASS] Data integrity status updated correctly")
    else:
        print("   [FAIL] Data integrity status update failed")
        return 1
    
    # Test 6: Update system health
    print("\n6. Testing system health update...")
    ss.update_system_health(uptime=3600.0, error_count=2, alert_count=1)
    print(f"   System health status: {ss.status['system_health']['status']}")
    print(f"   Uptime: {ss.status['system_health']['uptime']}")
    if ss.status['system_health']['status'] == 'HEALTHY':
        print("   [PASS] System health updated correctly")
    else:
        print("   [FAIL] System health update failed")
        return 1
    
    # Test 7: Get overall status
    print("\n7. Testing overall status calculation...")
    overall = ss.get_overall_status()
    print(f"   Overall status: {overall}")
    if overall == 'SECURE':
        print("   [PASS] Overall status calculated correctly")
    else:
        print("   [FAIL] Overall status calculation failed")
        return 1
    
    # Test 8: Test critical status
    print("\n8. Testing critical status detection...")
    ss.update_risk_control_status(kill_switch_active=True, position_limits=True, daily_loss=True)
    overall = ss.get_overall_status()
    print(f"   Overall status with kill switch: {overall}")
    if overall == 'CRITICAL':
        print("   [PASS] Critical status detected correctly")
    else:
        print("   [FAIL] Critical status not detected")
        return 1
    
    # Reset for next test
    ss.update_risk_control_status(kill_switch_active=False, position_limits=True, daily_loss=True)
    
    # Test 9: Get status summary
    print("\n9. Testing status summary...")
    summary = ss.get_status_summary()
    print(f"   Summary keys: {list(summary.keys())}")
    if 'overall_status' in summary and 'components' in summary:
        print("   [PASS] Status summary generated correctly")
    else:
        print("   [FAIL] Status summary generation failed")
        return 1
    
    # Test 10: Get GUI display data
    print("\n10. Testing GUI display data...")
    gui_data = ss.get_gui_display_data()
    print(f"   GUI data keys: {list(gui_data.keys())}")
    print(f"   Status color: {gui_data['status_color']}")
    if 'status_color' in gui_data and 'encryption' in gui_data:
        print("   [PASS] GUI display data generated correctly")
    else:
        print("   [FAIL] GUI display data generation failed")
        return 1
    
    # Test 11: Test warning status
    print("\n11. Testing warning status detection...")
    ss.update_system_health(uptime=3600.0, error_count=15, alert_count=3)
    overall = ss.get_overall_status()
    print(f"   Overall status with high errors: {overall}")
    if overall == 'CRITICAL':
        print("   [PASS] Warning/critical status detected correctly")
    else:
        print("   [FAIL] Warning/critical status not detected")
        return 1
    
    # Reset
    ss.update_system_health(uptime=3600.0, error_count=2, alert_count=1)
    
    # Test 12: Persistence
    print("\n12. Testing status persistence...")
    saved = ss.save_to_file("test_security_status.json")
    print(f"   Saved: {saved}")
    
    ss2 = SecurityStatus()
    loaded = ss2.load_from_file("test_security_status.json")
    print(f"   Loaded: {loaded}")
    
    if saved and loaded:
        print("   [PASS] Status persistence works correctly")
    else:
        print("   [FAIL] Status persistence failed")
        return 1
    
    # Cleanup
    if os.path.exists("test_security_status.json"):
        os.remove("test_security_status.json")
    
    # Test 13: Global instance
    print("\n13. Testing global security status instance...")
    global_ss = get_security_status()
    if global_ss:
        print("   [PASS] Global instance works")
    else:
        print("   [FAIL] Global instance failed")
        return 1
    
    # Test 14: Unknown status handling
    print("\n14. Testing unknown status handling...")
    ss3 = SecurityStatus()
    overall = ss3.get_overall_status()
    print(f"   Overall status (new instance): {overall}")
    # Note: Due to default True values, status may be WARNING or UNKNOWN
    if overall in ['UNKNOWN', 'WARNING']:
        print("   [PASS] Unknown/Warning status handled correctly")
    else:
        print("   [FAIL] Unknown/Warning status not handled")
        return 1
    
    # Test 15: Data integrity with disabled components
    print("\n15. Testing data integrity with disabled components...")
    ss.update_data_integrity_status(validation=False, freshness=True, reconciliation=True)
    overall = ss.get_overall_status()
    print(f"   Overall status with disabled validation: {overall}")
    if overall == 'WARNING':
        print("   [PASS] Disabled component status detected correctly")
    else:
        print("   [FAIL] Disabled component status not detected")
        return 1
    
    print(f"\n{'='*60}")
    print("[PASS] All security status display tests passed!")
    return 0

if __name__ == '__main__':
    sys.exit(test_security_status_display())
