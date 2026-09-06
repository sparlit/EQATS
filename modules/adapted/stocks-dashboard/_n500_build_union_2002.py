#!/usr/bin/env python
# Merge the full Nifty/CNX-500 ever-member union 2002 -> date, resolving era symbols to
# CURRENT symbols so it joins to fundamentals (which are keyed by today's tickers).
# Sources:
#   _n500_pre2008_union.json  (679 era syms, 2002-2006 htm captures)
#   _full_union_2008_v2.json  (818 era syms, 2008-01 -> 2015-03)
#   _full_union_2015_v3.json  (977 CURRENT syms, 2015 -> date)
# Rename layer: _rename_map.json (era->current, 796) + _rename_alias.json if present.
import json, os

def load(f):
    return json.load(open(f))

def main():
    pre = set(load('_n500_pre2008_union.json'))
    u08 = set(load('_full_union_2008_v2.json'))
    u15 = set(load('_full_union_2015_v3.json'))

    rmap = load('_rename_map.json')  # era -> current
    # chase rename chains to a fixed point
    def resolve(s):
        seen = set()
        while s in rmap and s not in seen:
            seen.add(s)
            s = rmap[s]
        return s

    era = pre | u08                      # era-symbol sources
    era_resolved = {resolve(s) for s in era}
    full = era_resolved | u15            # u15 already current

    # diagnostics
    mapped = sum(1 for s in era if s in rmap)
    print(f'pre-2008 era union : {len(pre)}')
    print(f'2008-2015 era union: {len(u08)}')
    print(f'2015-date current  : {len(u15)}')
    print(f'era total (pre|u08): {len(era)}  ({mapped} had a rename-map entry)')
    print(f'era resolved->curr : {len(era_resolved)}')
    print(f'--- ')
    print(f'FULL 2002-date UNION (current syms): {len(full)}')
    # what pre/08 adds beyond the 2015 union (the genuinely-new pre-2015 names)
    new_pre2015 = sorted(era_resolved - u15)
    print(f'names present pre-2015 but NOT in 2015-date union: {len(new_pre2015)}')
    print('sample:', new_pre2015[:30])

    json.dump(sorted(full), open('_full_union_2002.json', 'w'), indent=0)
    json.dump(new_pre2015, open('_full_union_2002_pre2015only.json', 'w'), indent=0)
    print('\nwrote _full_union_2002.json + _full_union_2002_pre2015only.json')

if __name__ == '__main__':
    main()
