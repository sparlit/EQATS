"""
Data Backup Systems Module
Implements backup and restore functionality for critical data.
"""

import os
import shutil
import sqlite3
import json
import hashlib
from datetime import datetime as dt, timedelta
from typing import Dict, Any, Optional, List
import zipfile
import pathlib


class BackupManager:
    """
    Manages backup and restore operations for critical data.
    """
    
    def __init__(self, backup_dir: str = "backups"):
        self.backup_dir = backup_dir
        self.backup_prefix = "forexscalpper_backup"
        
        # Files/directories to backup
        self.backup_sources = {
            'database': 'forexscalpper.db',
            'positions': 'positions.json',
            'orders': 'orders.json',
            'models': 'models/'
        }
        
        # Files to exclude (secrets, configs with passwords)
        self.exclude_files = ['.env', '.env.example', 'secrets.json']
        
        # Backup retention
        self.max_backups = 10  # Keep last 10 backups
        self.max_age_days = 30  # Delete backups older than 30 days
        
        # Ensure backup directory exists
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def create_backup(self, backup_name: str = None) -> Dict[str, Any]:
        """
        Create a backup of all critical data.
        
        Args:
            backup_name: Optional custom backup name
            
        Returns:
            Backup result dict
        """
        result = {
            'success': False,
            'backup_id': None,
            'backup_path': None,
            'timestamp': dt.now().isoformat(),
            'files_backed_up': [],
            'errors': []
        }
        
        try:
            # Generate backup name
            if backup_name is None:
                timestamp = dt.now().strftime("%Y%m%d_%H%M%S_%f")  # Include microseconds
                backup_name = f"{self.backup_prefix}_{timestamp}"
            
            backup_path = os.path.join(self.backup_dir, backup_name)
            os.makedirs(backup_path, exist_ok=True)
            
            # Backup database
            db_result = self._backup_database(backup_path)
            if db_result['success']:
                result['files_backed_up'].append(db_result['file'])
            else:
                result['errors'].append(f"Database backup failed: {db_result['error']}")
            
            # Backup JSON files
            for key, source in self.backup_sources.items():
                if key == 'database':
                    continue
                if key == 'models':
                    continue  # Handle models separately
                
                if os.path.exists(source):
                    try:
                        dest = os.path.join(backup_path, os.path.basename(source))
                        shutil.copy2(source, dest)
                        result['files_backed_up'].append(dest)
                    except Exception as e:
                        result['errors'].append(f"Failed to backup {source}: {e}")
            
            # Backup models directory
            if os.path.exists('models/'):
                try:
                    models_backup = os.path.join(backup_path, 'models')
                    shutil.copytree('models/', models_backup, dirs_exist_ok=True)
                    result['files_backed_up'].append(models_backup)
                except Exception as e:
                    result['errors'].append(f"Failed to backup models: {e}")
            
            # Create backup manifest
            manifest = {
                'backup_id': backup_name,
                'timestamp': dt.now().isoformat(),
                'files_backed_up': result['files_backed_up'],
                'checksums': self._calculate_checksums(result['files_backed_up'])
            }
            
            manifest_path = os.path.join(backup_path, 'backup_manifest.json')
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)
            
            result['files_backed_up'].append(manifest_path)
            result['success'] = True
            result['backup_id'] = backup_name
            result['backup_path'] = backup_path
            
            # Clean up old backups
            self._cleanup_old_backups()
            
        except Exception as e:
            result['errors'].append(f"Backup creation failed: {e}")
        
        return result
    
    def _backup_database(self, backup_path: str) -> Dict[str, Any]:
        """
        Backup SQLite database using SQLite's backup API.
        
        Args:
            backup_path: Path to backup directory
            
        Returns:
            Backup result
        """
        result = {
            'success': False,
            'file': None,
            'error': None
        }
        
        db_source = self.backup_sources['database']
        
        if not os.path.exists(db_source):
            result['error'] = f"Database file not found: {db_source}"
            return result
        
        try:
            # Use SQLite's online backup API
            dest_path = os.path.join(backup_path, os.path.basename(db_source))
            
            source_conn = sqlite3.connect(db_source)
            dest_conn = sqlite3.connect(dest_path)
            
            # Perform backup
            source_conn.backup(dest_conn)
            
            dest_conn.close()
            source_conn.close()
            
            result['success'] = True
            result['file'] = dest_path
            
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def _calculate_checksums(self, file_paths: List[str]) -> Dict[str, str]:
        """Calculate SHA256 checksums for files."""
        checksums = {}
        for file_path in file_paths:
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()
                        checksums[file_path] = file_hash
                except Exception:
                    pass
        return checksums
    
    def restore_backup(self, backup_id: str, restore_to_original: bool = True) -> Dict[str, Any]:
        """
        Restore data from a backup.
        
        Args:
            backup_id: Backup ID (directory name)
            restore_to_original: If True, restore to original locations
            
        Returns:
            Restore result dict
        """
        result = {
            'success': False,
            'backup_id': backup_id,
            'files_restored': [],
            'errors': []
        }
        
        backup_path = os.path.join(self.backup_dir, backup_id)
        
        if not os.path.exists(backup_path):
            result['errors'].append(f"Backup not found: {backup_id}")
            return result
        
        try:
            # Load manifest
            manifest_path = os.path.join(backup_path, 'backup_manifest.json')
            if os.path.exists(manifest_path):
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
            else:
                manifest = None
            
            # Restore database
            db_backup = os.path.join(backup_path, self.backup_sources['database'])
            if os.path.exists(db_backup):
                if restore_to_original:
                    # First backup current database
                    current_backup = f"{self.backup_sources['database']}.pre_restore"
                    if os.path.exists(self.backup_sources['database']):
                        shutil.copy2(self.backup_sources['database'], current_backup)
                    
                    # Restore database
                    shutil.copy2(db_backup, self.backup_sources['database'])
                    result['files_restored'].append(self.backup_sources['database'])
            
            # Restore JSON files
            for key, source in self.backup_sources.items():
                if key == 'database':
                    continue
                if key == 'models':
                    continue
                
                backup_file = os.path.join(backup_path, os.path.basename(source))
                if os.path.exists(backup_file) and restore_to_original:
                    shutil.copy2(backup_file, source)
                    result['files_restored'].append(source)
            
            # Restore models
            models_backup = os.path.join(backup_path, 'models')
            if os.path.exists(models_backup) and restore_to_original:
                if os.path.exists('models/'):
                    shutil.rmtree('models/')
                shutil.copytree(models_backup, 'models/')
                result['files_restored'].append('models/')
            
            # Verify checksums if manifest available
            if manifest and 'checksums' in manifest:
                verification = self._verify_checksums(manifest['checksums'], backup_path)
                if not verification['all_valid']:
                    result['errors'].append(f"Checksum verification failed: {verification['invalid_files']}")
            
            result['success'] = True
            
        except Exception as e:
            result['errors'].append(f"Restore failed: {e}")
        
        return result
    
    def _verify_checksums(self, expected_checksums: Dict[str, str], backup_path: str) -> Dict[str, Any]:
        """Verify file checksums against expected values."""
        result = {
            'all_valid': True,
            'invalid_files': []
        }
        
        for file_path, expected_hash in expected_checksums.items():
            file_name = os.path.basename(file_path)
            full_path = os.path.join(backup_path, file_name)
            
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'rb') as f:
                        actual_hash = hashlib.sha256(f.read()).hexdigest()
                    
                    if actual_hash != expected_hash:
                        result['all_valid'] = False
                        result['invalid_files'].append(file_name)
                except Exception:
                    result['all_valid'] = False
                    result['invalid_files'].append(file_name)
        
        return result
    
    def _cleanup_old_backups(self):
        """Remove old backups based on retention policy."""
        try:
            backups = self.list_backups()
            
            # Sort by timestamp (newest first)
            backups.sort(key=lambda x: x['timestamp'], reverse=True)
            
            # Keep only max_backups
            if len(backups) > self.max_backups:
                for backup in backups[self.max_backups:]:
                    backup_path = backup['path']
                    try:
                        shutil.rmtree(backup_path)
                    except Exception as e:
                        print(f"[WARNING] Failed to delete old backup {backup_path}: {e}")
            
            # Delete backups older than max_age_days
            cutoff_date = dt.now() - timedelta(days=self.max_age_days)
            for backup in backups:
                backup_date = dt.fromisoformat(backup['timestamp'])
                if backup_date < cutoff_date:
                    backup_path = backup['path']
                    try:
                        shutil.rmtree(backup_path)
                    except Exception as e:
                        print(f"[WARNING] Failed to delete old backup {backup_path}: {e}")
        
        except Exception as e:
            print(f"[ERROR] Backup cleanup failed: {e}")
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        List all available backups.
        
        Returns:
            List of backup info dicts
        """
        backups = []
        
        if not os.path.exists(self.backup_dir):
            return backups
        
        for item in os.listdir(self.backup_dir):
            item_path = os.path.join(self.backup_dir, item)
            
            if os.path.isdir(item_path) and item.startswith(self.backup_prefix):
                # Try to load manifest
                manifest_path = os.path.join(item_path, 'backup_manifest.json')
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, 'r') as f:
                            manifest = json.load(f)
                        
                        backups.append({
                            'backup_id': item,
                            'timestamp': manifest.get('timestamp'),
                            'path': item_path,
                            'files_count': len(manifest.get('files_backed_up', []))
                        })
                    except Exception:
                        # Fallback to directory modification time
                        backups.append({
                            'backup_id': item,
                            'timestamp': dt.fromtimestamp(os.path.getmtime(item_path)).isoformat(),
                            'path': item_path,
                            'files_count': 0
                        })
        
        return backups
    
    def create_incremental_backup(self, base_backup_id: str = None) -> Dict[str, Any]:
        """
        Create an incremental backup (only changed files).
        
        Args:
            base_backup_id: Base backup to compare against
            
        Returns:
            Backup result dict
        """
        # For simplicity, implement as full backup for now
        # A true incremental backup would require file change tracking
        return self.create_backup()
    
    def backup_status(self) -> Dict[str, Any]:
        """
        Get backup system status.
        
        Returns:
            Status dict
        """
        backups = self.list_backups()
        
        return {
            'backup_dir': self.backup_dir,
            'total_backups': len(backups),
            'latest_backup': backups[0] if backups else None,
            'oldest_backup': backups[-1] if backups else None,
            'backup_sources': list(self.backup_sources.keys()),
            'max_backups': self.max_backups,
            'max_age_days': self.max_age_days
        }


# Global backup manager instance
_backup_manager = None

def get_backup_manager() -> BackupManager:
    """Get the global backup manager instance."""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager
