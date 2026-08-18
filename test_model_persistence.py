#!/usr/bin/env python3
"""
Test Model Persistence for Predictive Brain
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from predictive_brain import get_symbol_predictor, disable_all_predictors, get_all_predictor_info

def test_model_persistence():
    """Test model persistence functionality."""
    print("Testing model persistence implementation...")
    
    # Clean up any existing models
    disable_all_predictors()
    models_dir = Path("models")
    if models_dir.exists():
        # Clean up old test files
        for file in models_dir.glob("*.pkl"):
            file.unlink()
    
    # Test 1: Create predictor and check it's untrained
    print("\n1. Creating new predictor...")
    predictor = get_symbol_predictor('EURUSD')
    initial_accuracy = predictor.get_accuracy()
    print(f"   Initial accuracy: {initial_accuracy}%")
    print(f"   Total predictions: {predictor.total_predictions}")
    if initial_accuracy == 50.0 and predictor.total_predictions == 0:
        print("   [PASS] Predictor starts untrained")
    else:
        print("   [FAIL] Predictor not starting in expected state")
        assert False, "Test condition failed"
    
    # Test 2: Train the predictor
    print("\n2. Training predictor...")
    # Train with more data to get meaningful accuracy
    for i in range(10):
        predictor.predict([0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        predictor.learn_and_adjust(1.0)  # Train with bullish outcome
    print(f"   New accuracy: {predictor.get_accuracy()}%")
    print(f"   Total predictions: {predictor.total_predictions}")
    if predictor.total_predictions > 0:
        print("   [PASS] Predictor has training data")
    else:
        print("   [FAIL] Predictor has no training data")
        assert False, "Test condition failed"
    
    # Test 3: Check model was auto-saved
    print("\n3. Checking auto-save...")
    models_dir = Path("models")
    model_file = models_dir / "EURUSD_predictor.pkl"
    if model_file.exists():
        print(f"   [PASS] Model file created: {model_file}")
    else:
        print(f"   [FAIL] Model file not created")
        assert False, "Test condition failed"
    
    # Test 4: Clear registry
    print("\n4. Clearing predictor registry...")
    disable_all_predictors()
    print("   [PASS] Predictor registry cleared")
    
    # Test 5: Load model from disk
    print("\n5. Loading model from disk...")
    loaded_predictor = get_symbol_predictor('EURUSD')
    loaded_accuracy = loaded_predictor.get_accuracy()
    loaded_predictions = loaded_predictor.total_predictions
    print(f"   Loaded accuracy: {loaded_accuracy}%")
    print(f"   Loaded predictions: {loaded_predictions}")
    
    if loaded_predictions > 0:
        print("   [PASS] Model loaded with training data")
    else:
        print("   [FAIL] Model did not load correctly")
        assert False, "Test condition failed"
    
    # Test 6: Verify model state
    print("\n6. Verifying model state...")
    internal_state = loaded_predictor.get_internal_state()
    if internal_state['training_cycles'] > 0:
        print("   [PASS] Model state preserved")
    else:
        print("   [FAIL] Model state not preserved")
        assert False, "Test condition failed"
    
    # Test 7: Get all predictor info
    print("\n7. Getting all predictor info...")
    info = get_all_predictor_info()
    if 'EURUSD' in info:
        print(f"   EURUSD info: {info['EURUSD']}")
        print("   [PASS] Predictor info accessible")
    else:
        print("   [FAIL] Predictor info not accessible")
        assert False, "Test condition failed"
    
    # Cleanup
    print("\n8. Cleaning up test files...")
    disable_all_predictors()
    model_file = models_dir / "EURUSD_predictor.pkl"
    if model_file.exists():
        model_file.unlink()
        print("   [PASS] Test files cleaned up")
    else:
        print("   [WARNING] Test file already removed")
    
    print(f"\n{'='*60}")
    print("[PASS] All model persistence tests passed!")
    # Clean test exit

if __name__ == '__main__':
    import sys
    sys.exit(test_model_persistence())
