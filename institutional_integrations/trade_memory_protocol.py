"""
Institutional Trade Memory & Reflection Protocol.
Inspired by tradememory-protocol: records post-mortem trade reflections,
calculates Maximum Favorable Excursion (MFE) / Maximum Adverse Excursion (MAE),
computes trade efficiency scores, and updates AI Brain Agent memory buffers.
"""

import datetime



class TradeMemoryReflectionProtocol:
    """Manages trade reflections, post-mortems, and cognitive memory buffers."""

    def __init__(self):
        self.memory_records = []
        self.reflections_log = []

    def log_reflection(
        self,
        ticket,
        symbol,
        direction,
        open_price,
        close_price,
        profit,
        reason,
        mfe=0.0,
        mae=0.0,
    ):
        """
        Calculates trade efficiency metrics and logs a post-mortem reflection record.
        """
        ts = datetime.datetime.now().isoformat()
        is_win = profit > 0.0

        # Calculate efficiency score
        efficiency = 100.0 if is_win else 0.0
        if mae > 0:
            efficiency = max(0.0, min(100.0, (mfe / (mae + 0.0001)) * 50.0))

        reflection_note = (
            f"Trade #{ticket} [{symbol} {direction}]: {'WIN' if is_win else 'LOSS'} (${profit:+.2f}). "
            f"Exit Reason: {reason}. Close: {close_price:.5f}. Efficiency Score: {efficiency:.1f}%."
        )

        record = {
            "timestamp": ts,
            "ticket": str(ticket),
            "symbol": symbol,
            "direction": direction,
            "open_price": open_price,
            "close_price": close_price,
            "profit": profit,
            "reason": reason,
            "is_win": is_win,
            "mfe": mfe,
            "mae": mae,
            "efficiency_score": round(efficiency, 1),
            "reflection_note": reflection_note,
        }

        self.memory_records.append(record)
        if len(self.memory_records) > 200:
            self.memory_records.pop(0)

        self.reflections_log.append(f"[{ts[:19]}] {reflection_note}")
        if len(self.reflections_log) > 100:
            self.reflections_log.pop(0)

        print(f"🧠 [TRADE MEMORY] {reflection_note}")

        # Update Vector Memory Buffer in local LLM if available
        try:
            import institutional_integrations.quantum_local_llm as qllm

            qllm.save_semantic_context(
                f"Trade_{ticket}", reflection_note, metadata=record
            )
        except Exception as e:
            print(f"⚠️ Trade memory LLM context store note: {e}")

        return record

    def get_summary(self, symbol=None):
        """Returns trade memory summary statistics."""
        records = self.memory_records
        if symbol:
            records = [r for r in records if r["symbol"] == symbol]

        if not records:
            return {
                "total_reflections": 0,
                "win_rate": 0.0,
                "avg_efficiency": 0.0,
                "recent_reflections": [],
            }

        wins = sum(1 for r in records if r["is_win"])
        win_rate = (wins / len(records)) * 100.0
        avg_eff = sum(r["efficiency_score"] for r in records) / len(records)

        return {
            "total_reflections": len(records),
            "win_rate": round(win_rate, 1),
            "avg_efficiency": round(avg_eff, 1),
            "recent_reflections": [r["reflection_note"] for r in records[-5:]],
        }


# Global Singleton Protocol Instance
global_trade_memory_protocol = TradeMemoryReflectionProtocol()
