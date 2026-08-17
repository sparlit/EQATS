#!/usr/bin/env python3
"""
Test Validation Feedback to GUI Implementation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validation_feedback_gui import ValidationFeedback, get_validation_feedback

def test_validation_feedback_gui():
    """Test validation feedback GUI functionality."""
    print("Testing validation feedback to GUI implementation...")
    
    # Test 1: Initialize validation feedback
    print("\n1. Testing validation feedback initialization...")
    vf = ValidationFeedback()
    print(f"   Feedback keys: {list(vf.feedback.keys())}")
    if len(vf.feedback) == 4:
        print("   [PASS] Validation feedback initialized correctly")
    else:
        print("   [FAIL] Validation feedback initialization failed")
        return 1
    
    # Test 2: Add order validation
    print("\n2. Testing order validation feedback...")
    vf.add_order_validation(
        valid=True,
        order={'symbol': 'EURUSD', 'lot_size': 0.1, 'direction': 'BUY'},
        errors=[],
        warnings=['Large lot size']
    )
    print(f"   Order validation status: {vf.feedback['order_validation']['status']}")
    print(f"   Warnings: {vf.feedback['order_validation']['warnings']}")
    if vf.feedback['order_validation']['status'] == 'VALID':
        print("   [PASS] Order validation feedback added correctly")
    else:
        print("   [FAIL] Order validation feedback failed")
        return 1
    
    # Test 3: Add position validation
    print("\n3. Testing position validation feedback...")
    vf.add_position_validation(
        valid=True,
        position_count=2,
        errors=[],
        warnings=['High exposure']
    )
    print(f"   Position validation status: {vf.feedback['position_validation']['status']}")
    print(f"   Position count: {vf.feedback['position_validation']['position_count']}")
    if vf.feedback['position_validation']['position_count'] == 2:
        print("   [PASS] Position validation feedback added correctly")
    else:
        print("   [FAIL] Position validation feedback failed")
        return 1
    
    # Test 4: Add data validation
    print("\n4. Testing data validation feedback...")
    vf.add_data_validation(
        valid=True,
        quality_score=95.0,
        symbols=['EURUSD', 'GBPUSD'],
        errors=[],
        warnings=['Slightly stale data']
    )
    print(f"   Data validation status: {vf.feedback['data_validation']['status']}")
    print(f"   Quality score: {vf.feedback['data_validation']['quality_score']}")
    if vf.feedback['data_validation']['quality_score'] == 95.0:
        print("   [PASS] Data validation feedback added correctly")
    else:
        print("   [FAIL] Data validation feedback failed")
        return 1
    
    # Test 5: Add risk validation
    print("\n5. Testing risk validation feedback...")
    vf.add_risk_validation(
        valid=True,
        limits_active=True,
        errors=[],
        warnings=['Near daily loss limit']
    )
    print(f"   Risk validation status: {vf.feedback['risk_validation']['status']}")
    print(f"   Limits active: {vf.feedback['risk_validation']['limits_active']}")
    if vf.feedback['risk_validation']['limits_active']:
        print("   [PASS] Risk validation feedback added correctly")
    else:
        print("   [FAIL] Risk validation feedback failed")
        return 1
    
    # Test 6: Get overall status
    print("\n6. Testing overall status calculation...")
    overall = vf.get_overall_status()
    print(f"   Overall status: {overall}")
    # All components are VALID, so overall should be VALID
    if overall == 'VALID':
        print("   [PASS] Overall status calculated correctly")
    else:
        print("   [FAIL] Overall status calculation failed")
        return 1
    
    # Test 7: Test invalid status
    print("\n7. Testing invalid status detection...")
    vf.add_order_validation(
        valid=False,
        order={'symbol': 'EURUSD', 'lot_size': 100.0},
        errors=['Lot size too large'],
        warnings=[]
    )
    overall = vf.get_overall_status()
    print(f"   Overall status with invalid order: {overall}")
    if overall == 'INVALID':
        print("   [PASS] Invalid status detected correctly")
    else:
        print("   [FAIL] Invalid status not detected")
        return 1
    
    # Reset for next test
    vf.add_order_validation(
        valid=True,
        order={'symbol': 'EURUSD', 'lot_size': 0.1},
        errors=[],
        warnings=[]
    )
    
    # Test 8: Get feedback summary
    print("\n8. Testing feedback summary...")
    summary = vf.get_feedback_summary()
    print(f"   Summary keys: {list(summary.keys())}")
    if 'overall_status' in summary and 'components' in summary:
        print("   [PASS] Feedback summary generated correctly")
    else:
        print("   [FAIL] Feedback summary generation failed")
        return 1
    
    # Test 9: Get GUI display data
    print("\n9. Testing GUI display data...")
    gui_data = vf.get_gui_display_data()
    print(f"   GUI data keys: {list(gui_data.keys())}")
    print(f"   Status color: {gui_data['status_color']}")
    if 'status_color' in gui_data and 'order_validation' in gui_data:
        print("   [PASS] GUI display data generated correctly")
    else:
        print("   [FAIL] GUI display data generation failed")
        return 1
    
    # Test 10: Get error count
    print("\n10. Testing error count...")
    vf.add_risk_validation(
        valid=False,
        limits_active=True,
        errors=['Daily loss limit exceeded'],
        warnings=[]
    )
    error_count = vf.get_error_count()
    print(f"   Error count: {error_count}")
    if error_count > 0:
        print("   [PASS] Error count calculated correctly")
    else:
        print("   [FAIL] Error count calculation failed")
        return 1
    
    # Test 11: Get warning count
    print("\n11. Testing warning count...")
    warning_count = vf.get_warning_count()
    print(f"   Warning count: {warning_count}")
    if warning_count > 0:
        print("   [PASS] Warning count calculated correctly")
    else:
        print("   [FAIL] Warning count calculation failed")
        return 1
    
    # Test 12: Clear feedback
    print("\n12. Testing feedback clearing...")
    vf.clear_feedback()
    print(f"   Feedback after clear: {list(vf.feedback.keys())}")
    if vf.feedback['order_validation']['status'] == 'UNKNOWN':
        print("   [PASS] Feedback cleared correctly")
    else:
        print("   [FAIL] Feedback clearing failed")
        return 1
    
    # Test 13: Persistence
    print("\n13. Testing feedback persistence...")
    vf.add_order_validation(
        valid=True,
        order={'symbol': 'EURUSD', 'lot_size': 0.1},
        errors=[],
        warnings=[]
    )
    
    saved = vf.save_to_file("test_validation_feedback.json")
    print(f"   Saved: {saved}")
    
    vf2 = ValidationFeedback()
    loaded = vf2.load_from_file("test_validation_feedback.json")
    print(f"   Loaded: {loaded}")
    
    if saved and loaded:
        print("   [PASS] Feedback persistence works correctly")
    else:
        print("   [FAIL] Feedback persistence failed")
        return 1
    
    # Cleanup
    if os.path.exists("test_validation_feedback.json"):
        os.remove("test_validation_feedback.json")
    
    # Test 14: Global instance
    print("\n14. Testing global validation feedback instance...")
    global_vf = get_validation_feedback()
    if global_vf:
        print("   [PASS] Global instance works")
    else:
        print("   [FAIL] Global instance failed")
        return 1
    
    # Test 15: All valid status
    print("\n15. Testing all valid status...")
    vf3 = ValidationFeedback()
    vf3.add_order_validation(True, {'symbol': 'EURUSD'}, [], [])
    vf3.add_position_validation(True, 1, [], [])
    vf3.add_data_validation(True, 100.0, ['EURUSD'], [], [])
    vf3.add_risk_validation(True, True, [], [])
    
    overall = vf3.get_overall_status()
    print(f"   Overall status (all valid): {overall}")
    if overall == 'VALID':
        print("   [PASS] All valid status detected correctly")
    else:
        print("   [FAIL] All valid status not detected")
        return 1
    
    print(f"\n{'='*60}")
    print("[PASS] All validation feedback GUI tests passed!")
    return 0

if __name__ == '__main__':
    sys.exit(test_validation_feedback_gui())
