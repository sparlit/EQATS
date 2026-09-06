#!/usr/bin/env python3
"""Run fetch_and_match.py across N parallel OS processes, each handling a disjoint slice
of the target list, writing to its own results file — no LLM/agent involvement, just plain
concurrent HTTP requests. Merge with merge_shards.py after.

Usage: python3 run_sharded.py <target_list.json> <out_prefix> <n_shards>
"""
import json, os, subprocess, sys, time

def main():
    target_list_path, out_prefix, n_shards = sys.argv[1], sys.argv[2], int(sys.argv[3])
    targets = json.load(open(target_list_path))
    symbols = list(targets.keys())  # preserves the newest-first order already baked into the file
    n = len(symbols)
    here = os.path.dirname(os.path.abspath(__file__))

    procs = []
    for i in range(n_shards):
        shard_syms = symbols[i::n_shards]   # interleaved, not contiguous blocks — keeps each
                                             # shard's own newest-first spread roughly even rather
                                             # than shard 0 getting all-2026 and shard N getting
                                             # all-2003 (which would defeat the newest-first intent)
        shard_targets = {s: targets[s] for s in shard_syms}
        shard_path = f'{out_prefix}_shard{i}_targets.json'
        json.dump(shard_targets, open(shard_path, 'w'))
        out_path = f'{out_prefix}_shard{i}.json'
        prog_path = f'{out_prefix}_shard{i}.log'
        cmd = [sys.executable, '-c', f"""
import sys; sys.path.insert(0, {here!r})
import fetch_and_match as m
m.main(target_list_path={shard_path!r}, out_path={out_path!r}, progress_path={prog_path!r})
print('SHARD {i} DONE')
"""]
        p = subprocess.Popen(cmd, cwd=os.path.dirname(os.path.dirname(here)))
        procs.append((i, p, len(shard_syms)))
        time.sleep(2)  # stagger startup so the initial cookie-session fetches don't all land at once

    print(f'launched {n_shards} shards for {n} symbols:')
    for i, p, cnt in procs:
        print(f'  shard {i}: pid={p.pid} symbols={cnt}')

if __name__ == '__main__':
    main()
