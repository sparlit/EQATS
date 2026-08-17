#!/usr/bin/env python3
"""
Test Logging Improvements Implementation
"""

import sys
import os
import tempfile
import shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logging_improvements import TradingLogger, get_trading_logger, setup_logging

def test_logging_improvements():
    """Test logging improvements functionality."""
    print("Testing logging improvements implementation...")
    
    # Create temporary directory for test logs
    test_dir = tempfile.mkdtemp(prefix="forexscalpper_log_test_")
    
    try:
        # Test 1: Initialize logger
        print("\n1. Testing logger initialization...")
        logger = TradingLogger(log_dir=test_dir, log_level="INFO")
        print(f"   Log directory: {test_dir}")
        print(f"   Logger level: {logger.log_level}")
        if logger.logger:
            print("   [PASS] Logger initialized correctly")
        else:
            print("   [FAIL] Logger initialization failed")
            return 1
        
        # Test 2: Component loggers
        print("\n2. Testing component loggers...")
        connector_logger = logger.get_component_logger("connector")
        risk_logger = logger.get_component_logger("risk_controls")
        
        if connector_logger and risk_logger:
            print("   [PASS] Component loggers created correctly")
        else:
            print("   [FAIL] Component loggers creation failed")
            return 1
        
        # Test 3: Log order
        print("\n3. Testing order logging...")
        logger.log_order("BUY", "EURUSD", 0.1, 1.0950, "FILLED", {"ticket": "12345"})
        print("   [PASS] Order logging works")
        
        # Test 4: Log position
        print("\n4. Testing position logging...")
        logger.log_position("EURUSD", "BUY", 0.1, 1.0950, 1.0960, 10.0)
        print("   [PASS] Position logging works")
        
        # Test 5: Log risk event
        print("\n5. Testing risk event logging...")
        logger.log_risk_event("LIMIT_BREACH", "GBPUSD", {"limit": 5.0, "current": 5.5})
        print("   [PASS] Risk event logging works")
        
        # Test 6: Log system event
        print("\n6. Testing system event logging...")
        logger.log_system_event("STARTUP", "SUCCESS", {"version": "1.0"})
        print("   [PASS] System event logging works")
        
        # Test 7: Log error
        print("\n7. Testing error logging...")
        try:
            raise ValueError("Test error")
        except Exception as e:
            logger.log_error("test_component", e, {"context": "test"})
        print("   [PASS] Error logging works")
        
        # Test 8: Log performance metric
        print("\n8. Testing performance metric logging...")
        logger.log_performance("latency", 50.0, "ms")
        print("   [PASS] Performance metric logging works")
        
        # Test 9: Log data event
        print("\n9. Testing data event logging...")
        logger.log_data_event("FETCH", "EURUSD", {"latency": 30, "quality": 95})
        print("   [PASS] Data event logging works")
        
        # Test 10: Change log level
        print("\n10. Testing log level change...")
        logger.set_log_level("DEBUG")
        if logger.log_level == 10:  # DEBUG level
            print("   [PASS] Log level changed correctly")
        else:
            print("   [FAIL] Log level change failed")
            return 1
        
        # Test 11: Get log files
        print("\n11. Testing log file paths...")
        log_files = logger.get_log_files()
        print(f"   Log files: {list(log_files.keys())}")
        if len(log_files) == 4:
            print("   [PASS] Log file paths retrieved correctly")
        else:
            print("   [FAIL] Log file paths retrieval failed")
            return 1
        
        # Test 12: Verify log files created
        print("\n12. Testing log file creation...")
        for log_type, file_path in log_files.items():
            if os.path.exists(file_path):
                print(f"   {log_type}: exists")
            else:
                print(f"   {log_type}: not found")
        
        if all(os.path.exists(fp) for fp in log_files.values()):
            print("   [PASS] All log files created")
        else:
            print("   [FAIL] Some log files not created")
            return 1
        
        # Test 13: Global logger
        print("\n13. Testing global logger instance...")
        global_logger = get_trading_logger(log_dir=test_dir)
        if global_logger:
            print("   [PASS] Global logger instance works")
        else:
            print("   [FAIL] Global logger instance failed")
            return 1
        
        # Test 14: Setup logging function
        print("\n14. Testing setup_logging function...")
        setup_logger = setup_logging(log_dir=test_dir, log_level="INFO")
        if setup_logger:
            print("   [PASS] setup_logging function works")
        else:
            print("   [FAIL] setup_logging function failed")
            return 1
        
        print(f"\n{'='*60}")
        print("[PASS] All logging improvements tests passed!")
        return 0
        
    finally:
        # Cleanup
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == '__main__':
    sys.exit(test_logging_improvements())
