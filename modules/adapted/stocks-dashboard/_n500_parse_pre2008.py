#!/usr/bin/env python
# Parse pre-2008 CNX-500 .htm constituent captures -> era-symbol lists per date.
# Table layout: repeating [Company Name, Industry Name, Symbol, Series].
import re, json, glob, os

def clean(c):
    c = re.sub('<[^>]+>', '', c)
    c = c.replace('&nbsp;', ' ').replace('&amp;', '&').strip()
    return c

def parse_htm(path):
    raw = open(path, encoding='utf-8', errors='replace').read()
    cells = [clean(x) for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', raw, re.I | re.S)]
    # find the "Symbol" / "Series" header anchor
    syms = []
    # locate index of a cell that == 'Symbol' followed by 'Series'
    start = None
    for i in range(len(cells) - 1):
        if cells[i] == 'Symbol' and cells[i + 1] == 'Series':
            start = i + 2
            break
    if start is None:
        return []
    # from start, walk in groups of 4: company, industry, symbol, series
    i = start
    while i + 3 < len(cells) + 1 and i + 2 < len(cells):
        sym = cells[i + 2] if i + 2 < len(cells) else ''
        ser = cells[i + 3] if i + 3 < len(cells) else ''
        # symbol looks like a ticker (uppercase alnum/&-), series in EQ/BE/etc
        if re.fullmatch(r'[A-Z0-9&\-\.]{1,20}', sym) and ser in ('EQ', 'BE', 'BT', 'BZ', 'SM'):
            syms.append(sym)
            i += 4
        else:
            # try to resync: advance by 1
            i += 1
            # bail if we've clearly left the table
            if len(syms) > 20 and (i - start) > len(syms) * 4 + 40:
                break
    return syms

def main():
    per_date = {}
    for p in sorted(glob.glob('_n500_pre2008/cnx500_*.htm')):
        d = re.search(r'(\d{8})', os.path.basename(p)).group(1)
        s = parse_htm(p)
        per_date[d] = sorted(set(s))
        print(f'{d}: {len(per_date[d])} symbols  ({os.path.basename(p)})')
    json.dump(per_date, open('_n500_pre2008_lists.json', 'w'), indent=0)
    uni = sorted(set().union(*[set(v) for v in per_date.values() if v]))
    json.dump(uni, open('_n500_pre2008_union.json', 'w'), indent=0)
    print(f'\nDATES parsed: {sum(1 for v in per_date.values() if v)}/{len(per_date)}')
    print(f'PRE-2008 ERA-SYMBOL UNION: {len(uni)}')

if __name__ == '__main__':
    main()
