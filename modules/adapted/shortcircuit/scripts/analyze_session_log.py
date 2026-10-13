import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


#!/usr/bin/env python3
import os
import re
import sys
from collections import defaultdict
from datetime import datetime


def normalize_symbol(sym):
    return sym.replace("NSE:", "").replace("-EQ", "").replace("-IQ", "").strip()


def parse_log_file(filepath):
    # Regexes
    line_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - (INFO|WARNING|ERROR|CRITICAL) - (.*)"
    )

    # Event matchers
    re.compile(r"SCAN #(\d+)")
    candidate_re = re.compile(r"\[CANDIDATE\] NSE:([^ ]+) \| (.*)")
    quality_skip_re = re.compile(r"\[SKIP\] Quality Reject: NSE:([^ ]+) \| (.*)")
    reject_re = re.compile(r"\[REJECTED\] ([^ ]+) \| Scan#\d+ \| FAILED at (.*)")
    momentum_block_re = re.compile(r"MOMENTUM BLOCK NSE:([^ ]+) (.*)")
    god_mode_re = re.compile(r"\[OK\] GOD MODE SIGNAL: NSE:([^ ]+) \| (.*)")
    gate_add_re = re.compile(r"\[GATE\] Added NSE:([^ ]+) to Validation Gate(.*)")
    gate_pass_re = re.compile(r"✅ \[VALIDATED\] NSE:([^ ]+) (.*)")
    entry_re = re.compile(r"(?:✅ \[ENTRY COMPLETE\]|\[ENTRY\]) (?:NSE:)?([A-Z0-9_\-]+) (.*)")
    re.compile(r"\[EXIT\] (?:NSE:)?([^ ]+) (.*)")
    pnl_re = re.compile(r"Phase 69 Outcome recorded for (?:NSE:)?([^ ]+): ₹(-?\d+\.\d+)")
    sync_re = re.compile(r"💰 CAPITAL SYNC \| .* \| slot=OCCUPIED → (?:NSE:)?([^ ]+)")

    # Events grouped by symbol. list of dicts: {'time': str, 'type': str, 'msg': str}
    traces = defaultdict(list)
    pnls = {}

    # General stats
    stats = {
        "total_scanned": 0,
        "quality_skips": 0,
        "god_mode_passes": 0,
        "entries": 0,
        "rejections_by_gate": defaultdict(int),
    }

    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    with open(filepath, encoding="utf-8") as f:
        for line in f:
            m = line_re.match(line)
            if not m:
                continue

            tstamp, level, msg = m.groups()

            # PnL Outcome
            pnl_m = pnl_re.search(msg)
            if pnl_m:
                sym = normalize_symbol(pnl_m.group(1))
                val = float(pnl_m.group(2))
                pnls[sym] = val
                traces[sym].append(
                    {"time": tstamp, "type": "PNL", "msg": f"Outcome Recorded: ₹{val:.2f}"}
                )
                continue

            # Candidate
            cand_m = candidate_re.search(msg)
            if cand_m:
                sym = normalize_symbol(cand_m.group(1))
                traces[sym].append(
                    {
                        "time": tstamp,
                        "type": "SCAN",
                        "msg": f"Gain: {cand_m.group(2).split('|')[0].strip()}",
                    }
                )
                stats["total_scanned"] += 1
                continue

            # Quality Skip
            qskip_m = quality_skip_re.search(msg)
            if qskip_m:
                sym = normalize_symbol(qskip_m.group(1))
                traces[sym].append(
                    {"time": tstamp, "type": "REJECTED", "msg": f"Quality Skip: {qskip_m.group(2)}"}
                )
                stats["quality_skips"] += 1
                continue

            # Momentum Block
            mom_m = momentum_block_re.search(msg)
            if mom_m:
                sym = normalize_symbol(mom_m.group(1))
                traces[sym].append(
                    {"time": tstamp, "type": "REJECTED", "msg": f"Momentum Block: {mom_m.group(2)}"}
                )
                continue

            # Standard Reject
            rej_m = reject_re.search(msg)
            if rej_m:
                sym = normalize_symbol(rej_m.group(1))
                reason = rej_m.group(2)
                traces[sym].append(
                    {"time": tstamp, "type": "REJECTED", "msg": f"FAILED at {reason}"}
                )
                stats["rejections_by_gate"][reason] += 1
                continue

            # God Mode Pass
            gm_m = god_mode_re.search(msg)
            if gm_m:
                sym = normalize_symbol(gm_m.group(1))
                details = gm_m.group(2)
                traces[sym].append(
                    {"time": tstamp, "type": "PASSED_GATES", "msg": f"Logic Passed: {details}"}
                )
                stats["god_mode_passes"] += 1
                continue

            # Added to Focus Engine
            ga_m = gate_add_re.search(msg)
            if ga_m:
                sym = normalize_symbol(ga_m.group(1))
                traces[sym].append(
                    {
                        "time": tstamp,
                        "type": "VALIDATION_WAIT",
                        "msg": f"Waiting for Focus form Trigger {ga_m.group(2)}",
                    }
                )
                continue

            # Validation Execution
            val_m = gate_pass_re.search(msg)
            if val_m:
                sym = normalize_symbol(val_m.group(1))
                traces[sym].append(
                    {"time": tstamp, "type": "TRIGGERED", "msg": f"Trigger hit! {val_m.group(2)}"}
                )
                continue

            # Entry Complete
            ent_m = entry_re.search(msg)
            if ent_m:
                sym = normalize_symbol(ent_m.group(1))
                traces[sym].append(
                    {"time": tstamp, "type": "ENTRY", "msg": f"Position Entered: {ent_m.group(2)}"}
                )
                stats["entries"] += 1
                continue

                traces[sym].append(
                    {"time": tstamp, "type": "EXIT", "msg": f"Position Closed: {ex_m.group(2)}"}
                )
                continue

            # Capital Sync (Inferred Entry)
            sync_m = sync_re.search(msg)
            if sync_m:
                sym = normalize_symbol(sync_m.group(1))
                # Only add as inferred entry if we haven't seen an entry or inferred entry for this symbol yet
                if not any(ev["type"] in ["ENTRY", "INFERRED_ENTRY"] for ev in traces[sym]):
                    traces[sym].append(
                        {
                            "time": tstamp,
                            "type": "INFERRED_ENTRY",
                            "msg": "Position detected via Capital Sync (Orphaned/Prev Session)",
                        }
                    )
                continue

    return traces, stats, pnls


def generate_markdown(filepath, traces, stats, pnls):
    date_str = os.path.basename(filepath).split("_")[0]
    out_path = f"reports/session_analysis_{date_str}.md"
    os.makedirs("reports", exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Detailed Session Analysis: {date_str}\n\n")

        f.write("## Executive Summary\n")
        f.write(f"- **Total Scan Hits**: {stats['total_scanned']}\n")
        f.write(f"- **Quality Pre-Filter Skips**: {stats['quality_skips']}\n")
        f.write(f"- **Scanner Gates Passed (God Mode)**: {stats['god_mode_passes']}\n")
        f.write(f"- **Live Entries Taken**: {stats['entries']}\n\n")

        f.write("## Gate Rejection Breakdown\n")
        for gate, count in sorted(
            stats["rejections_by_gate"].items(), key=lambda x: x[1], reverse=True
        ):
            f.write(f"- **{gate}**: {count} rejections\n")
        f.write("\n---\n\n")

        f.write("## Validated Trade Traces (Noise Filtered)\n")
        f.write(
            "> Only displaying symbols that passed validation gates and entered the Focus Engine.\n\n"
        )

        # Sort symbols by their first scan time
        sorted_syms = sorted(traces.keys(), key=lambda s: traces[s][0]["time"] if traces[s] else "")

        for sym in sorted_syms:
            events = traces[sym]

            # NOISE FILTER: Only include if the symbol reached PASSED_GATES, VALIDATION_WAIT, ENTRY, or INFERRED_ENTRY
            reached_validation = any(
                ev["type"] in ["PASSED_GATES", "VALIDATION_WAIT", "ENTRY", "INFERRED_ENTRY"]
                for ev in events
            )
            if not reached_validation:
                continue

            f.write(f"### 📊 `{sym}`")
            if sym in pnls:
                pnl_val = pnls[sym]
                color = "🟩" if pnl_val > 0 else "🟥"
                f.write(f" | PnL: {color} ₹{pnl_val:.2f}")
            f.write("\n")

            # Find the index of the first actual validation event (PASSED_GATES or VALIDATION_WAIT)
            first_val_idx = -1
            for i, ev in enumerate(events):
                if ev["type"] in ["PASSED_GATES", "VALIDATION_WAIT", "INFERRED_ENTRY"]:
                    first_val_idx = i
                    break

            if first_val_idx == -1:
                # Fallback just in case (should be caught by reached_validation above anyway)
                first_val_idx = 0

            # Filter events: we only care about the moment it hits validation and anything after
            filtered_events = events[first_val_idx:]

            # Print only strictly validated events (No SCAN, No REJECTED noise)
            whitelist = ["PASSED_GATES", "VALIDATION_WAIT", "TRIGGERED", "ENTRY", "EXIT", "PNL"]

            for ev in filtered_events:
                if ev["type"] not in whitelist and ev["type"] != "INFERRED_ENTRY":
                    continue

                emoji = "⏱️"
                if ev["type"] == "PASSED_GATES":
                    emoji = "✅"
                elif ev["type"] == "VALIDATION_WAIT":
                    emoji = "⏳"
                elif ev["type"] == "TRIGGERED":
                    emoji = "⚡"
                elif ev["type"] == "ENTRY":
                    emoji = "🚀"
                elif ev["type"] == "INFERRED_ENTRY":
                    emoji = "👻"
                elif ev["type"] == "EXIT":
                    emoji = "🏁"
                elif ev["type"] == "PNL":
                    emoji = "💰"

                f.write(f"  - `{ev['time']}` {emoji} **{ev['type']}**: {ev['msg']}\n")
            f.write("\n")

    print(f"✅ Report generated successfully at: {os.path.abspath(out_path)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_session_log.py <path_to_log_file>")
        sys.exit(1)

    log_path = sys.argv[1]
    print(f"Parsing logs from: {log_path}...")
    traces, stats, pnls = parse_log_file(log_path)
    if traces:
        generate_markdown(log_path, traces, stats, pnls)
