#!/usr/bin/env python3
"""
Test Data Backup Systems Implementation
"""

import sys
import os
import json
import tempfile
import shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backup_manager import BackupManager

def test_backup_manager():
    """Test backup manager functionality."""
    print("Testing data backup systems implementation...")
    
    # Create temporary directory for testing
    test_dir = tempfile.mkdtemp(prefix="forexscalpper_test_")
    original_dir = os.getcwd()
    
    try:
        os.chdir(test_dir)
        print(f"\nTest directory: {test_dir}")
        
        # Test 1: Initialize backup manager
        print("\n1. Testing backup manager initialization...")
        backup_dir = os.path.join(test_dir, "backups")
        bm = BackupManager(backup_dir=backup_dir)
        print(f"   Backup directory: {bm.backup_dir}")
        if os.path.exists(backup_dir):
            print("   [PASS] Backup manager initialized correctly")
        else:
            print("   [FAIL] Backup directory not created")
            return 1
        
        # Test 2: Create test data files
        print("\n2. Creating test data files...")
        os.makedirs("models", exist_ok=True)
        
        # Create a simple SQLite database
        import sqlite3
        conn = sqlite3.connect('forexscalpper.db')
        conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'test_data')")
        conn.commit()
        conn.close()
        
        # Create JSON files
        with open('positions.json', 'w') as f:
            json.dump({"test": "data"}, f)
        
        with open('orders.json', 'w') as f:
            json.dump({"orders": []}, f)
        
        # Create a dummy model file
        with open('models/test_model.pkl', 'w') as f:
            f.write("dummy model data")
        
        print("   [PASS] Test data files created")
        
        # Test 3: Create backup
        print("\n3. Testing backup creation...")
        result = bm.create_backup()
        print(f"   Success: {result['success']}")
        print(f"   Backup ID: {result['backup_id']}")
        print(f"   Files backed up: {len(result['files_backed_up'])}")
        if result['success'] and len(result['files_backed_up']) > 0:
            print("   [PASS] Backup created successfully")
        else:
            print("   [FAIL] Backup creation failed")
            return 1
        
        backup_id = result['backup_id']
        
        # Test 4: List backups
        print("\n4. Testing list backups...")
        backups = bm.list_backups()
        print(f"   Total backups: {len(backups)}")
        if len(backups) == 1:
            print("   [PASS] Backup listed correctly")
        else:
            print("   [FAIL] Backup listing incorrect")
            return 1
        
        # Test 5: Backup status
        print("\n5. Testing backup status...")
        status = bm.backup_status()
        print(f"   Total backups: {status['total_backups']}")
        print(f"   Latest backup: {status['latest_backup']['backup_id'] if status['latest_backup'] else None}")
        if status['total_backups'] == 1:
            print("   [PASS] Backup status correct")
        else:
            print("   [FAIL] Backup status incorrect")
            return 1
        
        # Test 6: Modify original data
        print("\n6. Modifying original data...")
        conn = sqlite3.connect('forexscalpper.db')
        conn.execute("INSERT INTO test VALUES (2, 'modified_data')")
        conn.commit()
        conn.close()
        
        with open('positions.json', 'w') as f:
            json.dump({"test": "modified"}, f)
        
        print("   [PASS] Data modified")
        
        # Test 7: Restore backup
        print("\n7. Testing backup restore...")
        restore_result = bm.restore_backup(backup_id, restore_to_original=True)
        print(f"   Success: {restore_result['success']}")
        print(f"   Files restored: {len(restore_result['files_restored'])}")
        if restore_result['success'] and len(restore_result['files_restored']) > 0:
            print("   [PASS] Backup restored successfully")
        else:
            print("   [FAIL] Backup restore failed")
            return 1
        
        # Test 8: Verify restored data
        print("\n8. Verifying restored data...")
        with open('positions.json', 'r') as f:
            restored_data = json.load(f)
        
        if restored_data.get('test') == 'data':  # Should be original, not modified
            print("   [PASS] Data restored correctly")
        else:
            print("   [FAIL] Data not restored correctly")
            return 1
        
        # Test 9: Create multiple backups
        print("\n9. Testing multiple backups...")
        bm.max_backups = 10  # Reset to allow multiple backups
        bm.max_age_days = 365  # Disable age-based cleanup
        
        for i in range(3):
            result = bm.create_backup()
            print(f"   Created backup {i+1}: {result['backup_id']}")
        
        backups = bm.list_backups()
        print(f"   Total backups: {len(backups)}")
        if len(backups) >= 2:  # Should have at least 2 (original + at least 1 new)
            print("   [PASS] Multiple backups created")
        else:
            print("   [FAIL] Multiple backups not created correctly")
            return 1
        
        # Test 10: Backup cleanup
        print("\n10. Testing backup cleanup...")
        bm.max_backups = 2  # Set low limit to test cleanup
        bm._cleanup_old_backups()
        
        backups_after = bm.list_backups()
        print(f"   Backups after cleanup: {len(backups_after)}")
        if len(backups_after) <= 2:
            print("   [PASS] Old backups cleaned up")
        else:
            print("   [FAIL] Backup cleanup failed")
            return 1
        
        # Test 11: Backup manifest verification
        print("\n11. Testing backup manifest...")
        result = bm.create_backup()
        backup_path = result['backup_path']
        manifest_path = os.path.join(backup_path, 'backup_manifest.json')
        
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            print(f"   Manifest keys: {list(manifest.keys())}")
            if 'backup_id' in manifest and 'timestamp' in manifest:
                print("   [PASS] Backup manifest created correctly")
            else:
                print("   [FAIL] Backup manifest incomplete")
                return 1
        else:
            print("   [FAIL] Backup manifest not found")
            return 1
        
        # Test 12: Checksum calculation
        print("\n12. Testing checksum calculation...")
        test_file = os.path.join(test_dir, "test_checksum.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        
        checksums = bm._calculate_checksums([test_file])
        print(f"   Checksums calculated: {len(checksums)}")
        if len(checksums) == 1:
            print("   [PASS] Checksums calculated correctly")
        else:
            print("   [FAIL] Checksums not calculated")
            return 1
        
        # Test 13: Backup without database
        print("\n13. Testing backup without database...")
        os.remove('forexscalpper.db')
        result = bm.create_backup()
        print(f"   Success: {result['success']}")
        print(f"   Errors: {result['errors']}")
        # Should still succeed, just without database
        if result['success']:
            print("   [PASS] Backup works without database")
        else:
            print("   [FAIL] Backup failed without database")
            return 1
        
        # Test 14: Restore non-existent backup
        print("\n14. Testing restore non-existent backup...")
        result = bm.restore_backup("non_existent_backup")
        print(f"   Success: {result['success']}")
        print(f"   Errors: {result['errors']}")
        if not result['success'] and len(result['errors']) > 0:
            print("   [PASS] Non-existent backup handled correctly")
        else:
            print("   [FAIL] Non-existent backup not handled")
            return 1
        
        print(f"\n{'='*60}")
        print("[PASS] All backup systems tests passed!")
        return 0
        
    finally:
        # Cleanup
        os.chdir(original_dir)
        shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == '__main__':
    sys.exit(test_backup_manager())
