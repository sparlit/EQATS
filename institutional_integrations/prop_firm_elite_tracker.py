"""
PropFirm Tracker Elite & SignalPulse Multi-Account Sync Engine.
Provides log-based trade event parser, asynchronous catchup sync,
and consolidated multi-account challenge status aggregator.
"""

import time
import math
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("PropFirmTrackerElite")

class SignalPulseLogSyncParser:
    """
    Parses MetaTrader log line entries to extract trade open/close/modify events.
    """
    def parse_log_line(self, log_line: str) -> Optional[Dict[str, Any]]:
        line = log_line.strip()
        if not line or ("order" not in line.lower() and "deal" not in line.lower() and "trade" not in line.lower()):
            return None

        # Extract basic trade event tokens
        parts = line.split()
        timestamp_str = parts[0] if len(parts) > 0 else str(time.strftime("%Y.%m.%d %H:%M:%S"))

        direction = "BUY" if "buy" in line.lower() else ("SELL" if "sell" in line.lower() else "UNKNOWN")

        profit = 0.0
        if "profit:" in line.lower():
            try:
                profit_idx = line.lower().find("profit:")
                profit_str = line[profit_idx+7:].split()[0]
                profit = float(profit_str)
            except Exception:
                profit = 0.0

        return {
            "raw_line": line,
            "timestamp": timestamp_str,
            "direction": direction,
            "profit": profit,
            "parsed": True
        }

class PropFirmEliteMultiAccountAggregator:
    """
    Consolidated View Aggregator across N prop firm challenge accounts.
    """
    def aggregate_accounts(self, account_snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not account_snapshots:
            return {"total_accounts": 0, "accounts_passed": 0, "accounts_failed": 0, "summary": []}

        passed = sum(1 for a in account_snapshots if a.get("passed", False))
        failed = sum(1 for a in account_snapshots if a.get("failed", False))
        in_progress = len(account_snapshots) - (passed + failed)

        total_profit = sum(a.get("current_profit", 0.0) for a in account_snapshots)

        return {
            "total_accounts": len(account_snapshots),
            "accounts_passed": passed,
            "accounts_failed": failed,
            "accounts_in_progress": in_progress,
            "total_combined_profit": round(total_profit, 2),
            "account_summaries": account_snapshots
        }
