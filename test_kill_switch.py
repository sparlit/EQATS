#!/usr/bin/env python3
"""
Test Kill Switch Implementation
"""

from kill_switch import get_kill_switch, KillSwitchState, KillSwitchReason

def test_kill_switch():
    """Test kill switch functionality."""
    print("Testing kill switch implementation...")
    
    kill_switch = get_kill_switch()
    
    # Reset to normal state if currently activated
    if kill_switch.is_activated():
        print("\n[INFO] Resetting kill switch to NORMAL state before test...")
        kill_switch.deactivate(triggered_by="test_reset", reason="Pre-test reset")
    
    # Test 1: Initial state should be NORMAL
    print("\n1. Testing initial state...")
    initial_state = kill_switch.get_state()
    if initial_state == KillSwitchState.NORMAL:
        print(f"   Initial state: {initial_state.value} - PASS")
    else:
        print(f"   Initial state: {initial_state.value} - FAIL")
        return 1
    
    # Test 2: Check if activated should be False
    print("\n2. Testing is_activated (should be False)...")
    if not kill_switch.is_activated():
        print("   Kill switch not activated - PASS")
    else:
        print("   Kill switch activated - FAIL")
        return 1
    
    # Test 3: Activate kill switch
    print("\n3. Testing activation...")
    activated = kill_switch.activate(
        reason=KillSwitchReason.MANUAL,
        triggered_by="test_user",
        details="Test activation",
        positions_count=5,
        open_orders_count=2,
        equity=10000.0
    )
    if activated:
        print("   Kill switch activated - PASS")
    else:
        print("   Kill switch activation failed - FAIL")
        return 1
    
    # Test 4: Check if activated should be True
    print("\n4. Testing is_activated (should be True)...")
    if kill_switch.is_activated():
        print("   Kill switch activated - PASS")
    else:
        print("   Kill switch not activated - FAIL")
        return 1
    
    # Test 5: Get activation info
    print("\n5. Testing get_activation_info...")
    activation_info = kill_switch.get_activation_info()
    if activation_info and activation_info['state'] == 'KILL_SWITCH_ACTIVATED':
        print(f"   Activation info retrieved - PASS")
        print(f"   State: {activation_info['state']}")
        print(f"   Reason: {activation_info['reason']}")
        print(f"   Triggered by: {activation_info['triggered_by']}")
    else:
        print("   Activation info retrieval failed - FAIL")
        return 1
    
    # Test 6: Test order blocking
    print("\n6. Testing order blocking...")
    if not kill_switch.is_order_allowed('BUY', is_position_closing=False):
        print("   Risk-increasing order blocked - PASS")
    else:
        print("   Risk-increasing order allowed - FAIL")
        return 1
    
    # Test 7: Test position closing allowed
    print("\n7. Testing position closing allowed...")
    if kill_switch.is_order_allowed('SELL', is_position_closing=True):
        print("   Position-closing order allowed - PASS")
    else:
        print("   Position-closing order blocked - FAIL")
        return 1
    
    # Test 8: Deactivate kill switch
    print("\n8. Testing deactivation...")
    deactivated = kill_switch.deactivate(
        triggered_by="test_user",
        reason="Test complete"
    )
    if deactivated:
        print("   Kill switch deactivated - PASS")
    else:
        print("   Kill switch deactivation failed - FAIL")
        return 1
    
    # Test 9: Check if activated should be False again
    print("\n9. Testing is_activated (should be False)...")
    if not kill_switch.is_activated():
        print("   Kill switch not activated - PASS")
    else:
        print("   Kill switch still activated - FAIL")
        return 1
    
    # Test 10: Get recent events
    print("\n10. Testing get_recent_events...")
    events = kill_switch.get_recent_events(limit=2)
    if len(events) >= 2:
        print(f"   Retrieved {len(events)} events - PASS")
    else:
        print(f"   Retrieved {len(events)} events - FAIL")
        return 1
    
    print(f"\n{'='*60}")
    print("[PASS] All kill switch tests passed!")

if __name__ == '__main__':
    import sys
    sys.exit(test_kill_switch())
