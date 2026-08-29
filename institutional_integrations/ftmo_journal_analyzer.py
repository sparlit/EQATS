"""
FTMO Trade Journal Analyzer & QuantStats Performance Core.
Parses FTMO CSV / Excel trade journal exports and computes trade duration distributions,
profit factor, expectancy, holding time correlations, and equity curve analytics.
"""

import io
import math
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

logger = logging.getLogger("FTMOJournalAnalyzer")

class FTMOJournalAnalyzer:
    """
    Parses and analyzes FTMO CSV/Excel trade journal export files.
    """
    def parse_journal_file(self, content_bytes: bytes, filename: str = "export.csv") -> List[Dict[str, Any]]:
        trades = []
        if not PANDAS_AVAILABLE or not content_bytes:
            return trades

        try:
            if filename.endswith(".xlsx") or filename.endswith(".xls"):
                df = pd.read_excel(io.BytesIO(content_bytes))
            else:
                df = pd.read_csv(io.BytesIO(content_bytes))

            # Normalize column names
            df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

            for _, row in df.iterrows():
                pnl = float(row.get("profit", row.get("pnl", row.get("net_profit", 0.0))))
                trades.append({
                    "ticket": str(row.get("ticket", row.get("id", ""))),
                    "symbol": str(row.get("symbol", row.get("item", "EURUSD"))).upper(),
                    "type": str(row.get("type", row.get("action", "BUY"))).upper(),
                    "volume": float(row.get("volume", row.get("lots", 0.01))),
                    "open_price": float(row.get("open_price", row.get("price", 0.0))),
                    "close_price": float(row.get("close_price", row.get("close", 0.0))),
                    "profit": pnl,
                    "commission": float(row.get("commission", 0.0)),
                    "swap": float(row.get("swap", 0.0)),
                })
        except Exception as e:
            logger.error(f"Error parsing journal file {filename}: {e}")

        return trades

    def compute_journal_stats(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not trades:
            return {
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "net_profit": 0.0,
                "max_consecutive_losses": 0
            }

        pnls = [float(t.get("profit", 0.0)) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [abs(p) for p in pnls if p < 0]

        total_trades = len(pnls)
        win_count = len(wins)
        win_rate_pct = round((win_count / total_trades) * 100.0, 2) if total_trades > 0 else 0.0

        total_win = sum(wins)
        total_loss = sum(losses)
        profit_factor = round(total_win / total_loss, 2) if total_loss > 0 else (99.0 if total_win > 0 else 0.0)

        net_profit = sum(pnls)
        expectancy = round(net_profit / total_trades, 2) if total_trades > 0 else 0.0

        # Max consecutive losses
        max_cons_losses = 0
        curr_cons = 0
        for p in pnls:
            if p < 0:
                curr_cons += 1
                max_cons_losses = max(max_cons_losses, curr_cons)
            else:
                curr_cons = 0

        return {
            "total_trades": total_trades,
            "win_rate_pct": win_rate_pct,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "net_profit": round(net_profit, 2),
            "max_consecutive_losses": max_cons_losses
        }
