#!/usr/bin/env python3
"""
Database Maintenance Script
Runs SQLite VACUUM and other maintenance operations during scheduled maintenance windows.
This should NOT be run during live trading as VACUUM locks the entire database.
"""

import sqlite3
import datetime
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import config


def backup_database(db_path: str) -> str:
    """
    Create a backup of the database before maintenance.
    
    Args:
        db_path: Path to the database file
        
    Returns:
        Path to the backup file
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_{timestamp}"
    
    if os.path.exists(db_path):
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✅ Database backed up to: {backup_path}")
        return backup_path
    else:
        print(f"⚠️ Database file not found: {db_path}")
        return None


def vacuum_database(db_path: str) -> bool:
    """
    Run SQLite VACUUM to optimize and compact the database.
    
    WARNING: VACUUM locks the entire database. Do NOT run during live trading.
    
    Args:
        db_path: Path to the database file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"🧹 Starting VACUUM on {db_path}...")
        
        # Open database in exclusive mode for VACUUM
        conn = sqlite3.connect(db_path, isolation_level='EXCLUSIVE')
        cursor = conn.cursor()
        
        # Run VACUUM
        cursor.execute("VACUUM")
        
        conn.commit()
        conn.close()
        
        print("✅ VACUUM completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ VACUUM failed: {e}")
        return False


def analyze_database(db_path: str) -> dict:
    """
    Analyze database size and structure.
    
    Args:
        db_path: Path to the database file
        
    Returns:
        Dictionary with database statistics
    """
    try:
        if not os.path.exists(db_path):
            return {"error": "Database file not found"}
        
        file_size = os.path.getsize(db_path)
        file_size_mb = file_size / (1024 * 1024)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get table list
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        # Get row counts for each table
        table_stats = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            table_stats[table] = count
        
        conn.close()
        
        return {
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size_mb, 2),
            "tables": tables,
            "table_stats": table_stats
        }
        
    except Exception as e:
        return {"error": str(e)}


def reindex_database(db_path: str) -> bool:
    """
    Run SQLite REINDEX to rebuild database indexes.
    
    Args:
        db_path: Path to the database file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"🔄 Starting REINDEX on {db_path}...")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Reindex all indexes
        cursor.execute("REINDEX")
        
        conn.commit()
        conn.close()
        
        print("✅ REINDEX completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ REINDEX failed: {e}")
        return False


def check_integrity(db_path: str) -> bool:
    """
    Run SQLite integrity check.
    
    Args:
        db_path: Path to the database file
        
    Returns:
        True if integrity check passes, False otherwise
    """
    try:
        print(f"🔍 Starting integrity check on {db_path}...")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Run integrity check
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        
        conn.close()
        
        if result and result[0] == "ok":
            print("✅ Integrity check passed")
            return True
        else:
            print(f"❌ Integrity check failed: {result}")
            return False
            
    except Exception as e:
        print(f"❌ Integrity check failed: {e}")
        return False


def run_full_maintenance(db_path: str, backup: bool = True) -> bool:
    """
    Run full database maintenance: backup, check integrity, reindex, vacuum.
    
    Args:
        db_path: Path to the database file
        backup: Whether to create backup before maintenance
        
    Returns:
        True if all steps successful, False otherwise
    """
    print("=" * 60)
    print("DATABASE MAINTENANCE")
    print("=" * 60)
    print(f"Database: {db_path}")
    print(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Analyze before
    print("Database analysis before maintenance:")
    stats_before = analyze_database(db_path)
    if "error" not in stats_before:
        print(f"  File size: {stats_before['file_size_mb']} MB")
        print(f"  Tables: {', '.join(stats_before['tables'])}")
        print(f"  Table rows: {stats_before['table_stats']}")
    else:
        print(f"  Error: {stats_before['error']}")
        return False
    print()
    
    # Backup
    if backup:
        backup_path = backup_database(db_path)
        if not backup_path:
            print("❌ Backup failed, aborting maintenance")
            return False
    print()
    
    # Integrity check
    if not check_integrity(db_path):
        print("❌ Integrity check failed, aborting maintenance")
        return False
    print()
    
    # Reindex
    if not reindex_database(db_path):
        print("⚠️ REINDEX failed, continuing with VACUUM")
    print()
    
    # VACUUM
    if not vacuum_database(db_path):
        print("❌ VACUUM failed")
        return False
    print()
    
    # Analyze after
    print("Database analysis after maintenance:")
    stats_after = analyze_database(db_path)
    if "error" not in stats_after:
        print(f"  File size: {stats_after['file_size_mb']} MB")
        size_reduction = stats_before['file_size_mb'] - stats_after['file_size_mb']
        if size_reduction > 0:
            print(f"  Size reduction: {size_reduction:.2f} MB ({(size_reduction/stats_before['file_size_mb']*100):.1f}%)")
    print()
    
    print("=" * 60)
    print("✅ Database maintenance completed successfully")
    print("=" * 60)
    return True


def main():
    """Main entry point."""
    db_path = config.DB_PATH
    
    # Check if database exists
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return 1
    
    # Safety check: confirm maintenance mode
    print("⚠️  WARNING: This will run database maintenance operations.")
    print("⚠️  SQLite VACUUM locks the entire database.")
    print("⚠️  Do NOT run this during live trading!")
    print()
    
    response = input("Proceed with database maintenance? (yes/no): ")
    if response.lower() != 'yes':
        print("Maintenance cancelled")
        return 0
    
    # Run maintenance
    success = run_full_maintenance(db_path, backup=True)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
