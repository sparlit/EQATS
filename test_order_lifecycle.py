#!/usr/bin/env python3
"""
Test Order State Machine Implementation
"""

import sys
import os
import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from order_lifecycle import Order, OrderState, OrderStateMachine, OrderRegistry, OrderTransitionError

def test_order_state_machine():
    """Test order state machine functionality."""
    print("Testing order state machine implementation...")
    
    # Test 1: Valid state transitions
    print("\n1. Testing valid state transitions...")
    sm = OrderStateMachine()
    print(f"   Initial state: {sm.current_state.value}")
    
    # PENDING -> SUBMITTED
    sm.transition_to(OrderState.SUBMITTED, reason="Order submitted")
    print(f"   After submit: {sm.current_state.value}")
    assert sm.current_state == OrderState.SUBMITTED
    
    # SUBMITTED -> ACCEPTED
    sm.transition_to(OrderState.ACCEPTED, reason="Order accepted")
    print(f"   After accept: {sm.current_state.value}")
    assert sm.current_state == OrderState.ACCEPTED
    
    # ACCEPTED -> FILLED
    sm.transition_to(OrderState.FILLED, reason="Order filled")
    print(f"   After fill: {sm.current_state.value}")
    assert sm.current_state == OrderState.FILLED
    
    print("   [PASS] Valid state transitions work correctly")
    
    # Test 2: Invalid state transition
    print("\n2. Testing invalid state transition...")
    sm2 = OrderStateMachine()
    
    try:
        sm2.transition_to(OrderState.FILLED, reason="Direct fill")
        print("   [FAIL] Invalid transition was allowed")
        assert False, "Test condition failed"
    except OrderTransitionError as e:
        print(f"   Caught expected error: {e}")
        print("   [PASS] Invalid transition blocked")
    
    # Test 3: State checks
    print("\n3. Testing state checks...")
    sm3 = OrderStateMachine()
    print(f"   Can modify (PENDING): {sm3.can_modify()}")
    print(f"   Can cancel (PENDING): {sm3.can_cancel()}")
    print(f"   Is terminal (PENDING): {sm3.is_terminal()}")
    print(f"   Is active (PENDING): {sm3.is_active()}")
    
    sm3.transition_to(OrderState.SUBMITTED, reason="Submitted")
    sm3.transition_to(OrderState.ACCEPTED, reason="Accepted")
    sm3.transition_to(OrderState.FILLED, reason="Filled")
    
    print(f"   Can modify (FILLED): {sm3.can_modify()}")
    print(f"   Can cancel (FILLED): {sm3.can_cancel()}")
    print(f"   Is terminal (FILLED): {sm3.is_terminal()}")
    print(f"   Is active (FILLED): {sm3.is_active()}")
    
    if not sm3.can_modify() and not sm3.can_cancel() and sm3.is_terminal() and not sm3.is_active():
        print("   [PASS] State checks work correctly")
    else:
        print("   [FAIL] State checks incorrect")
        assert False, "Test condition failed"
    
    # Test 4: Order lifecycle
    print("\n4. Testing order lifecycle...")
    order = Order(symbol="EURUSD", order_type="BUY", lot_size=0.1, sl=1.0900, tp=1.1100)
    print(f"   Created order: {order.ticket}")
    print(f"   Initial state: {order.state_machine.current_state.value}")
    
    # Submit
    order.submit(price=1.0950)
    print(f"   After submit: {order.state_machine.current_state.value}")
    assert order.state_machine.current_state == OrderState.SUBMITTED
    
    # Accept
    order.accept(broker_ticket="12345")
    print(f"   After accept: {order.state_machine.current_state.value}")
    assert order.state_machine.current_state == OrderState.ACCEPTED
    
    # Fill
    order.fill(price=1.0952, quantity=0.1)
    print(f"   After fill: {order.state_machine.current_state.value}")
    assert order.state_machine.current_state == OrderState.FILLED
    
    print("   [PASS] Order lifecycle works correctly")
    
    # Test 5: Partial fill
    print("\n5. Testing partial fill...")
    order2 = Order(symbol="GBPUSD", order_type="SELL", lot_size=0.5)
    order2.submit()
    order2.accept()
    order2.fill(price=1.3000, quantity=0.3)
    print(f"   After partial fill: {order2.state_machine.current_state.value}")
    print(f"   Filled quantity: {order2.filled_quantity}")
    
    if order2.state_machine.current_state == OrderState.PARTIALLY_FILLED and order2.filled_quantity == 0.3:
        print("   [PASS] Partial fill works correctly")
    else:
        print("   [FAIL] Partial fill incorrect")
        assert False, "Test condition failed"
    
    # Test 6: Order cancellation
    print("\n6. Testing order cancellation...")
    order3 = Order(symbol="USDJPY", order_type="BUY", lot_size=0.1)
    order3.submit()
    can_cancel = order3.state_machine.can_cancel()
    print(f"   Can cancel (SUBMITTED): {can_cancel}")
    
    cancelled = order3.cancel(reason="User requested")
    print(f"   After cancel: {order3.state_machine.current_state.value}")
    
    if cancelled and order3.state_machine.current_state == OrderState.CANCELLED:
        print("   [PASS] Order cancellation works correctly")
    else:
        print("   [FAIL] Order cancellation failed")
        assert False, "Test condition failed"
    
    # Test 7: Order rejection
    print("\n7. Testing order rejection...")
    order4 = Order(symbol="BTCUSD", order_type="BUY", lot_size=0.01)
    order4.submit()
    rejected = order4.reject(reason="Insufficient funds", error_code="NO_MONEY")
    print(f"   After reject: {order4.state_machine.current_state.value}")
    print(f"   Error message: {order4.error_message}")
    
    if rejected and order4.state_machine.current_state == OrderState.REJECTED:
        print("   [PASS] Order rejection works correctly")
    else:
        print("   [FAIL] Order rejection failed")
        assert False, "Test condition failed"
    
    # Test 8: Order modification
    print("\n8. Testing order modification...")
    order5 = Order(symbol="EURUSD", order_type="BUY", lot_size=0.1, sl=1.0900, tp=1.1100)
    order5.submit()
    order5.accept()
    
    can_modify = order5.state_machine.can_modify()
    print(f"   Can modify (ACCEPTED): {can_modify}")
    
    modified = order5.modify(sl=1.0910, tp=1.1090)
    print(f"   After modify: SL={order5.sl}, TP={order5.tp}")
    
    if modified and order5.sl == 1.0910 and order5.tp == 1.1090:
        print("   [PASS] Order modification works correctly")
    else:
        print("   [FAIL] Order modification failed")
        assert False, "Test condition failed"
    
    # Test 9: Cannot modify terminal state
    print("\n9. Testing modification restriction on terminal state...")
    order6 = Order(symbol="EURUSD", order_type="BUY", lot_size=0.1)
    order6.submit()
    order6.accept()
    order6.fill(price=1.0950, quantity=0.1)
    
    can_modify = order6.state_machine.can_modify()
    print(f"   Can modify (FILLED): {can_modify}")
    
    if not can_modify:
        print("   [PASS] Modification correctly blocked in terminal state")
    else:
        print("   [FAIL] Modification allowed in terminal state")
        assert False, "Test condition failed"
    
    # Test 10: Order registry
    print("\n10. Testing order registry...")
    registry = OrderRegistry()
    
    order7 = Order(symbol="EURUSD", order_type="BUY", lot_size=0.1)
    order8 = Order(symbol="GBPUSD", order_type="SELL", lot_size=0.2)
    
    registry.add_order(order7)
    registry.add_order(order8)
    
    active_orders = registry.get_active_orders()
    print(f"   Active orders: {len(active_orders)}")
    
    if len(active_orders) == 2:
        print("   [PASS] Order registry works correctly")
    else:
        print("   [FAIL] Order registry incorrect")
        assert False, "Test condition failed"
    
    # Test 11: Order serialization
    print("\n11. Testing order serialization...")
    order_dict = order7.to_dict()
    print(f"   Serialized order keys: {list(order_dict.keys())}")
    
    restored_order = Order.from_dict(order_dict)
    print(f"   Restored order ticket: {restored_order.ticket}")
    print(f"   Restored order symbol: {restored_order.symbol}")
    
    if restored_order.ticket == order7.ticket and restored_order.symbol == order7.symbol:
        print("   [PASS] Order serialization works correctly")
    else:
        print("   [FAIL] Order serialization failed")
        assert False, "Test condition failed"
    
    # Test 12: State history
    print("\n12. Testing state history...")
    order9 = Order(symbol="EURUSD", order_type="BUY", lot_size=0.1)
    order9.submit()
    order9.accept()
    
    state_info = order9.state_machine.get_state_info()
    history = state_info['state_history']
    print(f"   State history length: {len(history)}")
    print(f"   Transitions: {[h['from_state'] + ' -> ' + h['to_state'] for h in history]}")
    
    if len(history) >= 2:
        print("   [PASS] State history tracked correctly")
    else:
        print("   [FAIL] State history not tracked")
        assert False, "Test condition failed"
    
    print(f"\n{'='*60}")
    print("[PASS] All order state machine tests passed!")
    # Clean test exit

if __name__ == '__main__':
    sys.exit(test_order_state_machine())
