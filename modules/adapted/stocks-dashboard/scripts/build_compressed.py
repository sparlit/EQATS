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
"""Build a single-file HTML dashboard with gzip+base64 embedded data, decompressed
   client-side via the browser's native DecompressionStream API."""
import base64
import gzip
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "stock_data.json"
OUT_HTML = ROOT / "docs" / "nse-bse-dashboard.html"

payload = json.loads(SRC.read_text())
start_ts = payload["startTs"]
gen_ts = payload["generatedAt"]
gen_date = datetime.fromtimestamp(gen_ts).strftime("%d %b %Y %H:%M")
start_date = datetime.fromtimestamp(start_ts).strftime("%d %b %Y")

DAY = 86400
compact_series = {}
# 52-week-high distance: max close in the last 365 calendar days from the snapshot,
# vs the latest close. Anchored at the snapshot date so the value is constant
# across the user's selected From/To dates (matches Screener / Yahoo convention).
end_ts = payload["endTs"]
year_ago_ts = end_ts - 365 * DAY
h52_count = 0
for tkr, pairs in payload["series"].items():
    ds, ps = [], []
    for ts, close in pairs:
        ds.append(int((ts - start_ts) // DAY))
        ps.append(round(close * 100))
    compact_series[tkr] = {"d": ds, "p": ps}

    # 52w-high pass — only meaningful with at least 30 data points in the last year
    last_year = [(t, c) for t, c in pairs if t >= year_ago_ts]
    if len(last_year) >= 30 and pairs:
        h52 = max(c for _, c in last_year)
        l52 = min(c for _, c in last_year)
        last = pairs[-1][1]
        d52 = (last - h52) / h52 * 100 if h52 else 0
        u52 = (last - l52) / l52 * 100 if l52 else 0  # distance ABOVE the 52-week low
        meta = payload["meta"].get(tkr)
        if meta is not None:
            meta["h52"] = round(h52, 2)
            meta["l52"] = round(l52, 2)
            meta["d52"] = round(d52, 2)
            meta["u52"] = round(u52, 2)
            meta["latest"] = round(last, 2)
            h52_count += 1
print(f"52w-high attached to {h52_count} stocks")

# --- market cap for the NSE-only cohort (shares from SHP filings x latest close) --------------
# Every other mcap on the site comes from ONE field: Mktcap in BSE's scrip master (fetch_all.py).
# A company NSE lists but BSE doesn't has no row there, so fetch_all falls through to its
# NSE-only branch and hardcodes mcap 0 — ~105 symbols, BSE Ltd and CDSL among them. Blank mcap
# also blanks P/E, P/S and P/B on the stock page, which all divide into it.
# The quarterly shareholding-pattern XBRL we already download carries the total share count,
# banked per symbol in scripts/shares_outstanding.json by fetch_shareholding.py, so
# mcap = shares x latest close closes the gap for free. Reproduces BSE's own figure to a
# median 0.08% on a 20-name check, so the two sources are interchangeable in practice.
# Fill-only: a real BSE mcap is never overwritten.
shares_path = ROOT / "scripts" / "shares_outstanding.json"
if shares_path.exists():
    try:
        shares = json.loads(shares_path.read_text(encoding="utf-8"))
        filled = 0
        for tkr, meta in payload["meta"].items():
            if meta.get("mcap") or not meta.get("latest"):
                continue
            got = shares.get(str(meta.get("symbol") or tkr.split(".")[0]).upper())
            if not got or not got[0]:
                continue
            mcap = got[0] * meta["latest"] / 1e7  # shares x rupees -> rupees crore
            if mcap <= 0:
                continue
            meta["mcap"] = round(mcap, 2)
            meta["mcapSrc"] = "shp:" + got[1]  # provenance — not a BSE-reported cap
            filled += 1
        print(f"mcap from SHP share counts: {filled} filled ({len(shares)} counts on file)")
    except Exception as e:
        print(f"WARN shares_outstanding unusable ({e}) — NSE-only caps stay blank")

# Historical index snapshots (per-rebalance constituent lists, NSE symbols only).
# Optional — if missing, the dashboard falls back to today's META.indices.
indices_history_path = ROOT / "scripts" / "indices_history.json"
indices_history = {}
if indices_history_path.exists():
    try:
        indices_history = json.loads(indices_history_path.read_text())
        n_snaps = sum(len(v) for v in indices_history.values())
        print(f"Indices history: {len(indices_history)} indices, {n_snaps} snapshots")
    except Exception as e:
        print(f"WARN: failed to load indices_history.json: {e}")

# F&O underlyings list (today's + optional history). History format mirrors
# indicesHistory: [{ effectiveDate, symbols: [...] }, ...] sorted ascending.
# When history is empty, the dashboard falls back to today's list for ALL dates
# (with a UI note about the limitation).
fno_today = []
fno_history = []
fno_list_path = ROOT / "scripts" / "fno_list.json"
fno_history_path = ROOT / "scripts" / "fno_history.json"
if fno_list_path.exists():
    fno = json.loads(fno_list_path.read_text())
    fno_today = fno.get("stocks", [])
    print(f"F&O today's list: {len(fno_today)} stocks (as of {fno.get('asOf')})")
if fno_history_path.exists():
    fno_history = json.loads(fno_history_path.read_text())
    print(f"F&O history: {len(fno_history)} snapshots")

compact = {
    "startTs": start_ts,
    "endTs": payload["endTs"],
    "generatedAt": gen_ts,
    "meta": payload["meta"],
    "series": compact_series,
    "indicesHistory": indices_history,
    "fnoToday": fno_today,
    "fnoHistory": fno_history,
}

raw_json = json.dumps(compact, separators=(",", ":")).encode("utf-8")
print(f"Raw JSON: {len(raw_json) / 1024 / 1024:.2f} MB  stocks={len(compact_series)}")

gz = gzip.compress(raw_json, compresslevel=9)
print(f"Gzipped (full): {len(gz) / 1024 / 1024:.2f} MB  (ratio {len(raw_json) / len(gz):.1f}x)")

# --- SLIM payload: metadata for every stock + ONLY the last RECENT_DAYS of prices.
#     The homepage paints from this (~1 MB) instead of the full ~17 MB, so a brand-new
#     visitor sees the dashboard instantly. The full history loads lazily (from the
#     stock_data.bin written below) only when a longer date range or the backtest needs it. ---
from bisect import bisect_left

RECENT_DAYS = 250
cutoff_off = int((payload["endTs"] - RECENT_DAYS * DAY - start_ts) // DAY)
recent_series = {}
for tkr, cs in compact_series.items():
    ds = cs["d"]
    i = bisect_left(ds, cutoff_off)
    if i < len(ds):
        recent_series[tkr] = {"d": ds[i:], "p": cs["p"][i:]}
slim = {
    "startTs": start_ts,
    "endTs": payload["endTs"],
    "generatedAt": gen_ts,
    "meta": payload["meta"],
    "series": recent_series,
    "indicesHistory": indices_history,
    "fnoToday": fno_today,
    "fnoHistory": fno_history,
    "recentCutoffOff": cutoff_off,
}
slim_json = json.dumps(slim, separators=(",", ":")).encode("utf-8")
slim_gz = gzip.compress(slim_json, compresslevel=9)
(OUT_HTML.parent / "dash_slim.bin").write_bytes(slim_gz)
print(
    f"Slim: raw {len(slim_json) / 1024 / 1024:.2f} MB -> gz {len(slim_gz) / 1024 / 1024:.2f} MB  "
    f"(last {RECENT_DAYS}d, {len(recent_series)} priced stocks, cutoff_off={cutoff_off})"
)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>STOCKSWORLD · Stocks</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="./theme.css" />
<script src="./theme.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root { --gain:#16a34a; --gain-bg:#dcfce7; --loss:#dc2626; --loss-bg:#fee2e2; }
  body { font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif; }
  table thead th { position:sticky; top:0; background:#f8fafc; z-index:10; }
  .gain{color:var(--gain);} .loss{color:var(--loss);}
  .chip-gain{background:var(--gain-bg);color:var(--gain);}
  .chip-loss{background:var(--loss-bg);color:var(--loss);}
  .scrollbar::-webkit-scrollbar{width:8px;height:8px;}
  .scrollbar::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:4px;}
  .scrollbar::-webkit-scrollbar-track{background:#f1f5f9;}
  #loadingOverlay{position:fixed;inset:0;background:#f8fafc;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:50;transition:opacity .3s;}
  .spinner{width:44px;height:44px;border:4px solid #e2e8f0;border-top-color:#2563eb;border-radius:50%;animation:spin 1s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg);}}
</style>
</head>
<body class="bg-slate-50 text-slate-800">

<div id="loadingOverlay">
  <div class="spinner"></div>
  <div class="mt-5 text-sm font-semibold text-slate-700">Delivering magic soon&hellip;</div>
  <div class="mt-1 text-xs text-slate-500" id="loadingStatus">Brewing your dashboard</div>
</div>

<div class="min-h-screen">
  <header class="sticky top-0 z-40 bg-white/90 backdrop-blur-md border-b border-slate-200 shadow-sm">
    <div class="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between gap-4">
      <a href="./index.html" class="flex items-center gap-2.5 shrink-0 group">
        <span class="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-600 text-white flex items-center justify-center font-extrabold text-[13px] shadow-md group-hover:scale-105 transition">SW</span>
        <span class="font-bold text-slate-900 tracking-tight hidden sm:block">STOCKS<span class="text-indigo-600">WORLD</span></span>
      </a>
      <div class="flex items-center gap-3 min-w-0">
        <nav></nav>
        <span class="text-[11px] text-slate-400 hidden xl:block shrink-0" id="lastUpdated">__START_DATE__ &rarr; __GEN_DATE__ IST</span>
      </div>
    </div>
  </header>

  <section class="max-w-7xl mx-auto px-6 py-6">
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-slate-700 uppercase tracking-wide">Filters</h2>
        <span class="text-xs text-slate-500" id="universeCount">Loading universe&hellip;</span>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-7 gap-3">
        <div class="md:col-span-1">
          <label class="block text-xs font-medium text-slate-600 mb-1">From Date</label>
          <input type="date" id="fromDate" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white" />
        </div>
        <div class="md:col-span-1">
          <label class="block text-xs font-medium text-slate-600 mb-1">To Date</label>
          <input type="date" id="toDate" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white" />
        </div>
        <div class="md:col-span-1 relative">
          <label class="block text-xs font-medium text-slate-600 mb-1">Market Cap (&#8377; Cr)</label>
          <button type="button" id="mcapTrigger"
                  class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white text-left flex justify-between items-center hover:bg-slate-50 focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
            <span id="mcapLabel" class="truncate">All market caps</span>
            <svg class="w-4 h-4 text-slate-400 ml-1 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          </button>
          <div id="mcapPanel" class="hidden absolute z-30 mt-1 w-64 bg-white border border-slate-200 rounded-lg shadow-lg p-2">
            <div class="flex justify-between text-[11px] text-slate-500 px-2 py-1 border-b border-slate-100 mb-1">
              <button type="button" id="mcapSelectAll" class="hover:text-blue-600 font-medium">Select all</button>
              <button type="button" id="mcapClear"     class="hover:text-blue-600 font-medium">Clear</button>
            </div>
            <label class="flex items-center gap-2 px-2 py-1 hover:bg-slate-50 rounded cursor-pointer text-sm"><input type="checkbox" class="mcap-cb rounded border-slate-300" data-bucket="below100"/>100 and below</label>
            <label class="flex items-center gap-2 px-2 py-1 hover:bg-slate-50 rounded cursor-pointer text-sm"><input type="checkbox" class="mcap-cb rounded border-slate-300" data-bucket="100to500"/>100 &ndash; 500</label>
            <label class="flex items-center gap-2 px-2 py-1 hover:bg-slate-50 rounded cursor-pointer text-sm"><input type="checkbox" class="mcap-cb rounded border-slate-300" data-bucket="500to1000"/>500 &ndash; 1,000</label>
            <label class="flex items-center gap-2 px-2 py-1 hover:bg-slate-50 rounded cursor-pointer text-sm"><input type="checkbox" class="mcap-cb rounded border-slate-300" data-bucket="1000to5000"/>1,000 &ndash; 5,000</label>
            <label class="flex items-center gap-2 px-2 py-1 hover:bg-slate-50 rounded cursor-pointer text-sm"><input type="checkbox" class="mcap-cb rounded border-slate-300" data-bucket="5000to20000"/>5,000 &ndash; 20,000</label>
            <label class="flex items-center gap-2 px-2 py-1 hover:bg-slate-50 rounded cursor-pointer text-sm"><input type="checkbox" class="mcap-cb rounded border-slate-300" data-bucket="above20000"/>20,000 and above</label>
          </div>
        </div>
        <div class="md:col-span-1">
          <label class="block text-xs font-medium text-slate-600 mb-1">Index</label>
          <select id="indexFilter" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white">
            <option value="all">All indices</option>
          </select>
        </div>
        <div class="md:col-span-1">
          <label class="block text-xs font-medium text-slate-600 mb-1">F&amp;O</label>
          <select id="fnoFilter" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white">
            <option value="all">All stocks</option>
            <option value="fno">F&amp;O stocks only</option>
          </select>
        </div>
        <div class="md:col-span-1">
          <label class="block text-xs font-medium text-slate-600 mb-1">Industry</label>
          <select id="sectorFilter" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white">
            <option value="all">All sectors</option>
          </select>
        </div>
        <div class="md:col-span-1 flex items-end">
          <button id="loadBtn" class="w-full bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white rounded-lg px-4 py-2 text-sm font-semibold shadow-sm transition">Load Data</button>
        </div>
      </div>
      <div class="flex flex-wrap gap-2 mt-4">
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-latest="1" title="Most recent trading day's move (vs the previous trading day's close)">Latest move</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-days="7">Last 7 days</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-days="30">Last 30 days</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-days="90">Last 90 days</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-days="365">1 year</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-days="1095">3 years</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-days="1825">5 years</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-days="3650">10 years</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-days="7300">20 years</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-since-1996="1">Since 1996</button>
        <button class="preset-btn text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-full px-3 py-1 font-medium" data-ytd="1">YTD</button>
      </div>
      <div class="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-slate-100">
        <span class="text-[11px] font-bold uppercase tracking-wide text-slate-400">My screens</span>
        <span id="msList" class="flex flex-wrap gap-2"></span>
        <button id="msSave" class="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 rounded-full px-3 py-1 font-semibold" title="Save the current filter combination (dates, mcap, index, F&amp;O, industry) under a name — synced to your other devices">+ Save current filters</button>
      </div>
    </div>
  </section>

  <section class="max-w-7xl mx-auto px-6 pb-6">
    <div class="grid grid-cols-2 md:grid-cols-7 gap-3" id="statsGrid"></div>
  </section>

  <!-- Backtest panel: pick top-N by screening returns, hold to a later date, see portfolio P&L -->
  <section class="max-w-7xl mx-auto px-6 pb-6">
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div class="flex items-center justify-between mb-3">
        <div>
          <h2 class="text-sm font-semibold text-slate-700 uppercase tracking-wide">Backtest</h2>
          <p class="text-[11px] text-slate-500 mt-0.5">Pick the top-N stocks by the From&rarr;To return, &ldquo;buy&rdquo; them equal-weighted on the To Date, sell on Hold&nbsp;Until. Returns shown.</p>
        </div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
        <div>
          <label class="block text-xs font-medium text-slate-600 mb-1">Top N (sorted by % Change)</label>
          <input type="number" id="backtestN" value="10" min="1" max="500" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white" />
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-600 mb-1">Hold Until</label>
          <input type="date" id="backtestHoldTo" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white" />
        </div>
        <div>
          <label class="block text-xs font-medium text-slate-600 mb-1">Capital (&#8377;)</label>
          <input type="text" id="backtestCapital" value="1,00,000" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm tabular-nums focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white" />
        </div>
        <div class="flex items-end">
          <button id="runBacktestBtn" class="w-full bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white rounded-lg px-4 py-2 text-sm font-semibold shadow-sm transition">Run Backtest</button>
        </div>
        <div class="flex items-end">
          <p class="text-[11px] text-slate-500 italic">Screen period = main From&rarr;To dates above. Buy date = To Date.</p>
        </div>
      </div>
      <div id="backtestResults" class="mt-5 hidden"></div>
    </div>
  </section>

  <section class="max-w-7xl mx-auto px-6 pb-10">
    <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-200 flex flex-wrap gap-3 justify-between items-center">
        <div>
          <h3 class="text-sm font-semibold text-slate-700 uppercase tracking-wide">Results</h3>
          <p class="text-xs text-slate-500 mt-0.5" id="resultCount">Pick dates + market cap, then click <span class="font-semibold">Load Data</span>.</p>
        </div>
        <div class="flex gap-2 items-center">
          <input type="text" id="searchBox" placeholder="Search symbol or company&hellip;" class="border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 w-64" />
          <button id="exportBtn" class="text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg px-3 py-1.5 font-medium">Export CSV</button>
        </div>
      </div>
      <div class="max-h-[640px] overflow-auto scrollbar">
        <table class="w-full text-sm">
          <thead class="bg-slate-50 text-slate-600 text-xs uppercase">
            <tr id="resultsHead">
              <th class="px-4 py-3 text-left font-semibold">#</th>
              <th class="px-4 py-3 text-left font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="symbol">Symbol <span class="sort-ind text-slate-300">&#8597;</span></th>
              <th class="px-4 py-3 text-left font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="name">Company <span class="sort-ind text-slate-300">&#8597;</span></th>
              <th class="px-4 py-3 text-left font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="sector">Industry <span class="sort-ind text-slate-300">&#8597;</span></th>
              <th class="px-4 py-3 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="mcap">Market Cap <span class="sort-ind text-slate-300">&#8597;</span><br><span class="normal-case text-slate-400 text-[10px] font-normal">(&#8377; Cr)</span></th>
              <th class="px-4 py-3 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="fromPrice">From Price <span class="sort-ind text-slate-300">&#8597;</span><br><span class="normal-case text-slate-400 text-[10px] font-normal">(&#8377;)</span></th>
              <th class="px-4 py-3 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="toPrice">To Price <span class="sort-ind text-slate-300">&#8597;</span><br><span class="normal-case text-slate-400 text-[10px] font-normal">(&#8377;)</span></th>
              <th class="px-4 py-3 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="changePercent">Change % <span class="sort-ind text-blue-600">&darr;</span></th>
              <th class="px-4 py-3 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="d52" title="Distance from 52-week high, anchored at snapshot date">From 52W <span class="sort-ind text-slate-300">&#8597;</span><br><span class="normal-case text-slate-400 text-[10px] font-normal">High</span></th>
            </tr>
          </thead>
          <tbody id="resultsBody" class="divide-y divide-slate-100">
            <tr><td colspan="9" class="text-center text-slate-400 py-16 text-sm">Loading stock data&hellip;</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <footer class="max-w-7xl mx-auto px-6 py-6 text-xs text-slate-400 text-center">
    Price data from Yahoo Finance &middot; Market caps from BSE &middot; Weekly closes 1996&ndash;2019, daily 2020&ndash;today &middot; NSE suffix .NS / BSE suffix .BO
  </footer>
</div>

<script>
let META = {}, SERIES = {}, UNIVERSE = [], START_TS = 0, END_TS = 0,
    INDICES_HISTORY = {}, FNO_TODAY = new Set(), FNO_HISTORY = [];
// Slim-first loading: SERIES initially holds only the last ~250 days (from dash_slim.bin).
// recentCutoffOff = the earliest day-offset present in the slim data; any query that reaches
// before it triggers a one-time lazy fetch of the full history from stock_data.bin.
let RECENT_CUTOFF_OFF = 0, FULL_LOADED = false, FULL_LOADING = null;
async function gunzipFetch(url) {
  const buf = await (await fetch(url)).arrayBuffer();
  const stream = new Blob([new Uint8Array(buf)]).stream().pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(stream).text());
}
// Lazily pull the FULL price history (only when a long-range query / backtest needs it).
async function ensureFull(statusFn) {
  if (FULL_LOADED) return true;
  if (!FULL_LOADING) FULL_LOADING = (async () => {
    if (statusFn) statusFn('Loading full history…');
    const D = await gunzipFetch('./stock_data.bin');   // full series, already built + cacheable
    SERIES = D.series;                                  // superset of the slim recent series
    FULL_LOADED = true;
  })().catch(e => { FULL_LOADING = null; throw e; });
  await FULL_LOADING;
  return FULL_LOADED;
}

// Return the set of NSE symbols that were in `indexName` on `dateISO`.
// Snapshots are stored ascending by effectiveDate and each snapshot is the
// membership FROM its effectiveDate onward (see build_n500_membership.py) —
// so pick the LAST snapshot with effectiveDate <= the user's date, exactly
// like the backtest engine's lastSnap(). Dates before the first capture fall
// back to the earliest snapshot (nearest in time).
function getIndexMembersAt(indexName, dateISO) {
  const snaps = INDICES_HISTORY[indexName];
  if (!snaps || !snaps.length) return null; // no history → fall back to current
  let best = null;
  for (const s of snaps) {
    if (s.effectiveDate <= dateISO) best = s;
    else break;
  }
  return new Set((best || snaps[0]).symbols);
}

// F&O membership at a given date — same lastSnap convention as indices.
// Without history snapshots, fall back to today's NSE F&O list.
function getFnoMembersAt(dateISO) {
  if (FNO_HISTORY && FNO_HISTORY.length) {
    let best = null;
    for (const s of FNO_HISTORY) {
      if (s.effectiveDate <= dateISO) best = s;
      else break;
    }
    return new Set((best || FNO_HISTORY[0]).symbols);
  }
  return FNO_TODAY;
}
const DAY = 86400;

async function loadAndInit() {
  const statusEl = document.getElementById('loadingStatus');
  try {
    const t0 = performance.now();
    statusEl.textContent = 'Loading…';
    await new Promise(r => requestAnimationFrame(() => setTimeout(r, 16)));

    // Slim payload: metadata + last ~250 days only (~1 MB). Full history is fetched
    // lazily by ensureFull() from stock_data.bin when a longer range / backtest needs it.
    const D = await gunzipFetch('./dash_slim.bin');
    META = D.meta; SERIES = D.series; START_TS = D.startTs; END_TS = D.endTs || D.generatedAt;
    RECENT_CUTOFF_OFF = D.recentCutoffOff || 0;
    UNIVERSE = Object.keys(META);
    // Historical index membership (per-rebalance snapshots). Optional.
    INDICES_HISTORY = D.indicesHistory || {};
    FNO_TODAY = new Set(D.fnoToday || []);
    FNO_HISTORY = D.fnoHistory || [];

    // Populate the dropdown using BSE's IndustryNew (granular: Pharma, Metals,
    // Chemicals, etc.) with a fallback to the broad sector or 'Uncategorized'.
    // The selected key is stored on each option's data-key for filtering.
    const indCounts = {};
    for (const t of UNIVERSE) {
      const m = META[t];
      const ind = (m.industry && m.industry.trim()) || m.sector || 'Uncategorized';
      indCounts[ind] = (indCounts[ind] || 0) + 1;
    }
    const sectorSel = document.getElementById('sectorFilter');
    // Sort: largest industry first so common ones surface
    Object.entries(indCounts)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .forEach(([ind, n]) => {
        const opt = document.createElement('option');
        opt.value = ind;
        opt.textContent = ind + '  (' + n.toLocaleString('en-IN') + ')';
        sectorSel.appendChild(opt);
      });

    // Index dropdown — fed by per-stock `indices` arrays (Nifty 500, etc.)
    const indexCounts = {};
    for (const t of UNIVERSE) {
      const arr = META[t].indices || [];
      for (const ix of arr) indexCounts[ix] = (indexCounts[ix] || 0) + 1;
    }
    const indexSel = document.getElementById('indexFilter');
    // Preferred ordering so the most common picks surface at the top
    const PREFERRED = ['Nifty 50','Nifty Next 50','Nifty 100','Nifty 200','Nifty 500',
                       'Nifty Midcap 50','Nifty Midcap 100','Nifty Midcap 150',
                       'Nifty Smallcap 50','Nifty Smallcap 100','Nifty Smallcap 250',
                       'Nifty LargeMidcap 250','Nifty MidSmallcap 400'];
    const inPref = PREFERRED.filter(x => indexCounts[x]);
    const rest   = Object.keys(indexCounts).filter(x => !PREFERRED.includes(x)).sort();
    for (const ix of inPref.concat(rest)) {
      const opt = document.createElement('option');
      opt.value = ix;
      opt.textContent = ix + '  (' + indexCounts[ix].toLocaleString('en-IN') + ')';
      indexSel.appendChild(opt);
    }

    const dt = ((performance.now() - t0) / 1000).toFixed(1);
    statusEl.textContent = 'Ready ✨';
    const priced = Object.keys(SERIES).length;
    const unpriced = UNIVERSE.length - priced;
    document.getElementById('universeCount').textContent =
      UNIVERSE.length.toLocaleString('en-IN') + ' NSE & BSE listings' +
      ' (' + priced.toLocaleString('en-IN') + ' with prices, ' + unpriced.toLocaleString('en-IN') + ' metadata-only)';

    // Default range: last 7 days
    const today = new Date();
    const weekAgo = new Date(); weekAgo.setDate(today.getDate() - 7);
    document.getElementById('toDate').value   = today.toISOString().split('T')[0];
    document.getElementById('fromDate').value = weekAgo.toISOString().split('T')[0];

    const ov = document.getElementById('loadingOverlay');
    ov.style.opacity = '0';
    setTimeout(() => ov.remove(), 300);

    loadData();
  } catch (err) {
    statusEl.innerHTML = 'Error: ' + (err && err.message ? err.message : err) +
      '<br><span class="text-[11px]">Your browser may not support DecompressionStream. Use Chrome 80+ / Edge / Safari 16+ / Firefox 113+.</span>';
    console.error(err);
  }
}

// Test a single mcap value against a single bucket key
function inMcapBucket(mcap, bucket) {
  if (bucket === 'below100')     return mcap > 0 && mcap <= 100;
  if (bucket === '100to500')     return mcap > 100    && mcap <= 500;
  if (bucket === '500to1000')    return mcap > 500    && mcap <= 1000;
  if (bucket === '1000to5000')   return mcap > 1000   && mcap <= 5000;
  if (bucket === '5000to20000')  return mcap > 5000   && mcap <= 20000;
  if (bucket === 'above20000')   return mcap > 20000;
  return false;
}
// True if mcap matches ANY bucket in the set. Empty set = no filter (all).
// All 6 buckets selected = also no filter (catches mcap=0/unknown stocks too,
// matching user intuition that "all checked" means "everything").
function inAnyMcapBucket(mcap, bucketSet) {
  if (!bucketSet || bucketSet.size === 0) return true;
  if (bucketSet.size >= 6) return true;
  for (const b of bucketSet) if (inMcapBucket(mcap, b)) return true;
  return false;
}

function firstOnOrAfter(arr, v) {
  let lo = 0, hi = arr.length - 1, ans = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (arr[mid] >= v) { ans = mid; hi = mid - 1; } else lo = mid + 1; }
  return ans;
}
function lastOnOrBefore(arr, v) {
  let lo = 0, hi = arr.length - 1, ans = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (arr[mid] <= v) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
  return ans;
}

let lastResults = [];

async function loadData() {
  const fromDate     = document.getElementById('fromDate').value;
  const toDate       = document.getElementById('toDate').value;
  const mcapBuckets  = getMcapBucketSet();   // Set of selected buckets (empty = all)
  const sectorFilter = document.getElementById('sectorFilter').value;
  const indexFilter  = document.getElementById('indexFilter').value;
  if (!fromDate || !toDate)                 return alert('Please select both From Date and To Date');
  // Allow From == To (means "show this day's 1-day move" — slide-back logic
  // below picks the previous trading day's close as the comparison point).
  if (new Date(fromDate) > new Date(toDate)) return alert('From Date must be on or before To Date');

  // Interpret user-picked dates as UTC midnight so they line up exactly with
  // Yahoo's day_offsets (which use UTC). Without 'Z' the browser would treat
  // "May 5" as IST midnight = May 4 18:30 UTC, landing on the WRONG offset.
  const fromTs = Math.floor(new Date(fromDate + 'T00:00:00Z').getTime() / 1000);
  const toTs   = Math.floor(new Date(toDate   + 'T23:59:59Z').getTime() / 1000);
  const fromDayOffset = Math.floor((fromTs - START_TS) / DAY);
  const toDayOffset   = Math.floor((toTs   - START_TS) / DAY);

  // If the window reaches before the slim recent-data cutoff, pull the FULL history once.
  // Short / default ranges stay instant on the slim data.
  if (fromDayOffset < RECENT_CUTOFF_OFF && !FULL_LOADED) {
    const rc = document.getElementById('resultCount');
    if (rc) rc.textContent = 'Loading full history…';
    try { await ensureFull(); } catch (e) { if (rc) rc.textContent = 'Could not load full history. Check your connection and retry.'; return; }
  }

  // Historical index membership at the user's From Date — so e.g. selecting
  // "Nifty 500 + 2021-Jan-01 → 2021-Dec-31" shows stocks that were in Nifty 500
  // back in 2021, not today's Nifty 500. Falls back to today's META.indices if
  // no history is available for the chosen index.
  const fnoFilter    = document.getElementById('fnoFilter').value;
  const histMembers = indexFilter !== 'all'
    ? getIndexMembersAt(indexFilter, fromDate)
    : null;
  const fnoMembers = fnoFilter === 'fno' ? getFnoMembersAt(fromDate) : null;
  const results = [];
  for (const ticker of UNIVERSE) {
    const m = META[ticker];
    if (!inAnyMcapBucket(m.mcap, mcapBuckets)) continue;
    if (indexFilter !== 'all') {
      if (histMembers) {
        const base = ticker.endsWith('.NS') ? ticker.slice(0, -3) : ticker;
        if (!histMembers.has(base)) continue;
      } else {
        if (!(m.indices || []).includes(indexFilter)) continue;
      }
    }
    if (fnoMembers) {
      const base = ticker.endsWith('.NS') ? ticker.slice(0, -3) : ticker;
      if (!fnoMembers.has(base)) continue;
    }
    const indKey = (m.industry && m.industry.trim()) || m.sector || 'Uncategorized';
    if (sectorFilter !== 'all' && indKey !== sectorFilter) continue;
    const ser = SERIES[ticker];
    // Base row — same shape regardless of whether we have prices.
    const row = {
      symbol: m.symbol, name: m.name,
      sector: indKey,                       // shown in the table chip
      sectorBroad: m.sector || '',           // kept for tooltip / CSV
      mcap: m.mcap,
      fromPrice: null, toPrice: null, changePercent: null,
      fromDate: null,  toDate: null,  noData: true,
      // 52-week-high distance, anchored at snapshot date (constant per stock)
      d52: (typeof m.d52 === 'number') ? m.d52 : null,
      h52: (typeof m.h52 === 'number') ? m.h52 : null,
    };
    if (ser) {
      // From-date semantics: anchor to the last trading day STRICTLY BEFORE
      // the from-date — i.e., the close right before the user's window opens.
      // This way "May 4 → May 5" reports the May 1 → May 5 window (covering
      // everything that happened ON May 4 and May 5) instead of just May 4
      // close → May 5 close (which would identical to "May 5 → May 5").
      let iFrom = lastOnOrBefore(ser.d, fromDayOffset - 1);
      let iTo   = lastOnOrBefore(ser.d, toDayOffset);
      // If iFrom resolves to nothing (from-date is before the very first data
      // point), fall back to the earliest entry so we still produce a row.
      if (iFrom === -1 && iTo !== -1 && iTo > 0) iFrom = 0;
      // If iFrom and iTo collapse (selected window covers ≤ 1 trading day),
      // slide iFrom back one more so we still report a 1-trading-day change.
      if (iFrom !== -1 && iTo !== -1 && iFrom === iTo && iFrom > 0) iFrom = iTo - 1;
      if (iFrom !== -1 && iTo !== -1 && iTo > iFrom) {
        const fromPrice = ser.p[iFrom] / 100;
        const toPrice   = ser.p[iTo]   / 100;
        if (fromPrice && toPrice) {
          row.fromPrice = fromPrice;
          row.toPrice   = toPrice;
          row.changePercent = ((toPrice - fromPrice) / fromPrice) * 100;
          row.fromDate = new Date((START_TS + ser.d[iFrom] * DAY) * 1000).toISOString().slice(0, 10);
          row.toDate   = new Date((START_TS + ser.d[iTo]   * DAY) * 1000).toISOString().slice(0, 10);
          row.noData = false;
          // Staleness flag: how far is the resolved To date from what the user
          // actually picked? If the gap is large (suspended / illiquid stock
          // that hasn't traded in weeks), flag the row so the user knows the
          // displayed change is stale rather than a fresh result.
          row.staleDays = Math.max(0, toDayOffset - ser.d[iTo]);
          row.fromGapDays = Math.max(0, (fromDayOffset - 1) - ser.d[iFrom]);
        }
      } else if (iFrom !== -1 && iFrom === iTo && iFrom === 0) {
        // Listing-day edge case: stock has only one entry inside the window
        // and there's nothing earlier. Show the listing-day price as "Day 1"
        // with no change figure, instead of an empty row.
        row.fromPrice = ser.p[iFrom] / 100;
        row.toPrice   = ser.p[iFrom] / 100;
        row.changePercent = null;
        row.fromDate = row.toDate = new Date((START_TS + ser.d[iFrom] * DAY) * 1000).toISOString().slice(0, 10);
        row.firstDay = true;
        row.noData = false;
      }
    }
    results.push(row);
  }
  lastResults = results;
  renderResults(results);
  updateStats(results);
}

// Mutable sort state (key = column data-sort, dir = 'asc'|'desc')
const SORT_STATE = { key: 'changePercent', dir: 'desc' };
const STRING_COLS = new Set(['symbol', 'name', 'sector']);

function compareRows(a, b, key, dir) {
  // Always push noData rows to the bottom for any sort.
  if (a.noData && !b.noData) return 1;
  if (b.noData && !a.noData) return -1;

  const av = a[key];
  const bv = b[key];

  // Null/undefined goes to bottom regardless of direction
  const aNull = (av == null || (typeof av === 'number' && isNaN(av)));
  const bNull = (bv == null || (typeof bv === 'number' && isNaN(bv)));
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;

  let cmp;
  if (STRING_COLS.has(key)) cmp = String(av).localeCompare(String(bv));
  else                       cmp = av - bv;
  return dir === 'asc' ? cmp : -cmp;
}

function renderResults(results) {
  const q = document.getElementById('searchBox').value.toLowerCase().trim();
  let f = results;
  if (q) f = f.filter(r => r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q) || (r.sector || '').toLowerCase().includes(q));
  f = f.slice();
  f.sort((a, b) => compareRows(a, b, SORT_STATE.key, SORT_STATE.dir));

  const tbody = document.getElementById('resultsBody');
  const MAX_ROWS = 500;
  const truncated = f.length > MAX_ROWS;
  const view = f.slice(0, MAX_ROWS);

  if (view.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-400 py-16 text-sm">No matching stocks. Adjust filters or search.</td></tr>';
  } else {
    const out = [];
    const DASH = '<span class="text-slate-400">\u2014</span>';
    for (let i = 0; i < view.length; i++) {
      const r = view[i];
      const mcap = r.mcap > 0 ? r.mcap.toLocaleString('en-IN', {maximumFractionDigits: 0}) : '\u2014';
      let fromCell, toCell, chgCell;
      if (r.noData) {
        fromCell = toCell = chgCell = DASH;
      } else if (r.firstDay) {
        // Stock has only one trading day inside the window (its listing day);
        // show the price but flag that no comparison is possible.
        fromCell = toCell = '&#8377;' + r.fromPrice.toFixed(2);
        chgCell  = '<span class="inline-flex items-center bg-blue-50 text-blue-700 rounded-md px-2 py-0.5 font-semibold text-xs" title="Stock\'s first trading day — no prior close to compare">Day 1</span>';
      } else {
        const cls = r.changePercent >= 0 ? 'chip-gain' : 'chip-loss';
        const arr = r.changePercent >= 0 ? '&#9650;' : '&#9660;';
        const sgn = r.changePercent >= 0 ? '+' : '';
        fromCell = '&#8377;' + r.fromPrice.toFixed(2);
        toCell   = '&#8377;' + r.toPrice.toFixed(2);
        // Append a small "stale" warning badge if the resolved To date is more
        // than 14 days before the user-picked To date — almost always means the
        // stock is suspended or hasn't traded recently. We still report the
        // change, just flag that it's not "fresh".
        const staleNote = (r.staleDays && r.staleDays > 14)
          ? '<span class="inline-flex items-center bg-amber-50 text-amber-700 rounded-md px-1.5 py-0.5 font-medium text-[10px] ml-1" title="Stock\'s last trade in this window was ' + r.staleDays + ' days before your To Date">stale</span>'
          : '';
        chgCell  = '<span class="inline-flex items-center gap-1 ' + cls + ' rounded-md px-2 py-0.5 font-semibold text-xs tabular-nums">' + arr + ' ' + sgn + r.changePercent.toFixed(2) + '%</span>' + staleNote;
      }
      // Screener.in URL: NSE symbols use the symbol itself; BSE-only stocks use
      // the numeric scrip code (Screener accepts both formats).
      const swKey = encodeURIComponent(r.symbol);
      const linkAttrs = 'href="./stock.html?sym=' + swKey + '" title="' + r.symbol + ' — full details on STOCKSWORLD"';
      const screenerAttrs = 'href="https://www.screener.in/company/' + swKey + '/" target="_blank" rel="noopener" title="' + r.symbol + ' on Screener.in"';
      // From-52w-high cell. d52 is always <= 0; closer to zero = closer to high.
      let h52Cell;
      if (typeof r.d52 !== 'number') {
        h52Cell = DASH;
      } else {
        // colour scale: 0% = green chip, deeper = red. tooltip shows the price.
        let cls;
        if (r.d52 >= -2)       cls = 'chip-gain';
        else if (r.d52 >= -10) cls = 'bg-amber-50 text-amber-700';
        else if (r.d52 >= -25) cls = 'bg-orange-50 text-orange-700';
        else                    cls = 'chip-loss';
        const titleAttr = r.h52 ? ' title="52W high: ₹' + r.h52.toFixed(2) + '"' : '';
        h52Cell = '<span class="inline-flex items-center ' + cls + ' rounded-md px-2 py-0.5 font-semibold text-xs tabular-nums"' + titleAttr + '>' + r.d52.toFixed(2) + '%</span>';
      }
      out.push(
        '<tr class="hover:bg-slate-50 transition' + (r.noData ? ' bg-slate-50/40' : '') + '">' +
        '<td class="px-4 py-3 text-slate-400 text-xs">' + (i + 1) + '</td>' +
        '<td class="px-4 py-3"><span class="sw-star" data-sym="' + r.symbol + '"></span> <a ' + linkAttrs + ' class="font-semibold text-slate-800 hover:text-blue-600 hover:underline">' + r.symbol + '</a> <a ' + screenerAttrs + ' class="text-slate-300 hover:text-blue-600 text-[10px] align-super">↗</a></td>' +
        '<td class="px-4 py-3"><a ' + linkAttrs + ' class="text-slate-700 hover:text-blue-600 hover:underline">' + r.name + '</a></td>' +
        '<td class="px-4 py-3"><span class="text-xs bg-slate-100 text-slate-600 rounded-md px-2 py-0.5">' + r.sector + '</span></td>' +
        '<td class="px-4 py-3 text-right text-slate-700 tabular-nums">' + mcap + '</td>' +
        '<td class="px-4 py-3 text-right text-slate-600 tabular-nums">' + fromCell + '</td>' +
        '<td class="px-4 py-3 text-right text-slate-800 font-medium tabular-nums">' + toCell + '</td>' +
        '<td class="px-4 py-3 text-right">' + chgCell + '</td>' +
        '<td class="px-4 py-3 text-right">' + h52Cell + '</td>' +
        '</tr>'
      );
    }
    tbody.innerHTML = out.join('');
  }
  const noDataCount = f.filter(r => r.noData).length;
  const noDataNote  = noDataCount ? ' &middot; <span class="text-slate-400">' + noDataCount.toLocaleString('en-IN') + ' without price data</span>' : '';
  document.getElementById('resultCount').innerHTML =
    '<span class="font-semibold text-slate-700">' + f.length.toLocaleString('en-IN') + '</span> stocks' + noDataNote +
    (truncated ? ' (showing top ' + MAX_ROWS + ' \u2014 use sort/search/filters to narrow)' : '');
}

function updateStats(results) {
  if (!results.length) { document.getElementById('statsGrid').innerHTML = ''; return; }
  const priced    = results.filter(r => !r.noData);
  const gainers   = priced.filter(r => r.changePercent > 0).length;
  const losers    = priced.filter(r => r.changePercent < 0).length;
  const unchanged = priced.length - gainers - losers;
  const noData    = results.length - priced.length;
  const avg       = priced.length ? priced.reduce((s, r) => s + r.changePercent, 0) / priced.length : 0;
  const top       = priced.length ? priced.reduce((m, r) => r.changePercent > m.changePercent ? r : m) : null;

  const card = (label, value, sub, cls = '') =>
    '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4">' +
    '<div class="text-[11px] text-slate-500 uppercase font-semibold tracking-wide">' + label + '</div>' +
    '<div class="text-xl font-bold mt-1 ' + cls + '">' + value + '</div>' +
    (sub ? '<div class="text-[11px] text-slate-400 mt-0.5">' + sub + '</div>' : '') +
    '</div>';

  const topCard = top ?
    '<div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4">' +
    '<div class="text-[11px] text-slate-500 uppercase font-semibold tracking-wide">Top Mover</div>' +
    '<div class="text-sm font-bold mt-1 truncate"><a href="./stock.html?sym=' + encodeURIComponent(top.symbol) + '" class="text-slate-800 hover:text-blue-600 hover:underline">' + top.symbol + '</a></div>' +
    '<div class="text-xs gain mt-0.5">+' + top.changePercent.toFixed(2) + '%</div></div>'
    : card('Top Mover', '\u2014', '');

  // Total = full row count = Gainers + Losers + Unchanged + No Data exactly.
  document.getElementById('statsGrid').innerHTML =
    card('Total Stocks', results.length.toLocaleString('en-IN'), 'in current view') +
    card('Gainers',   gainers.toLocaleString('en-IN'),   '', 'gain') +
    card('Losers',    losers.toLocaleString('en-IN'),    '', 'loss') +
    card('Unchanged', unchanged.toLocaleString('en-IN'), '0% change', 'text-slate-700') +
    card('No Data',   noData.toLocaleString('en-IN'),    'no price in range', 'text-slate-500') +
    card('Avg Change', priced.length ? ((avg >= 0 ? '+' : '') + avg.toFixed(2) + '%') : '\u2014',
         'across ' + priced.length.toLocaleString('en-IN') + ' priced', priced.length ? (avg >= 0 ? 'gain' : 'loss') : '') +
    topCard;
}

function exportCSV() {
  if (!lastResults.length) return alert('No data to export. Load data first.');
  const rows = [['Symbol','Company','Sector','Market Cap (Cr)','From Date','From Price','To Date','To Price','Change %','52W High','From 52W High %']];
  lastResults.forEach(r => rows.push([
    r.symbol, r.name, r.sector, r.mcap,
    r.fromDate || '', r.fromPrice != null ? r.fromPrice.toFixed(2) : '',
    r.toDate   || '', r.toPrice   != null ? r.toPrice.toFixed(2)   : '',
    r.changePercent != null ? r.changePercent.toFixed(2) : '',
    r.h52 != null ? r.h52.toFixed(2) : '',
    r.d52 != null ? r.d52.toFixed(2) : '',
  ]));
  const csv  = rows.map(row => row.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  a.download = 'stocksworld-stocks-' + document.getElementById('fromDate').value + '-to-' + document.getElementById('toDate').value + '.csv';
  a.click();
  URL.revokeObjectURL(url);
}

document.getElementById('loadBtn').addEventListener('click', loadData);
document.getElementById('searchBox').addEventListener('input', () => lastResults.length && renderResults(lastResults));

// Column-header click sort.
function updateSortIndicators() {
  document.querySelectorAll('#resultsHead th[data-sort]').forEach(th => {
    const ind = th.querySelector('.sort-ind');
    if (!ind) return;
    if (th.dataset.sort === SORT_STATE.key) {
      ind.textContent = SORT_STATE.dir === 'asc' ? '↑' : '↓';
      ind.classList.remove('text-slate-300');
      ind.classList.add('text-blue-600');
    } else {
      ind.textContent = '↕';
      ind.classList.add('text-slate-300');
      ind.classList.remove('text-blue-600');
    }
  });
}
document.querySelectorAll('#resultsHead th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    const key = th.dataset.sort;
    if (SORT_STATE.key === key) {
      SORT_STATE.dir = SORT_STATE.dir === 'asc' ? 'desc' : 'asc';
    } else {
      SORT_STATE.key = key;
      // String columns default to ascending; numeric default to descending
      SORT_STATE.dir = STRING_COLS.has(key) ? 'asc' : 'desc';
    }
    updateSortIndicators();
    if (lastResults.length) renderResults(lastResults);
  });
});
document.getElementById('exportBtn').addEventListener('click', exportCSV);

// --- Backtest engine -----------------------------------------------
function computeReturn(ticker, fromDate, toDate) {
  const ser = SERIES[ticker]; if (!ser) return null;
  const fromTs = Math.floor(new Date(fromDate + 'T00:00:00Z').getTime() / 1000);
  const toTs   = Math.floor(new Date(toDate   + 'T23:59:59Z').getTime() / 1000);
  const fromOff = Math.floor((fromTs - START_TS) / DAY);
  const toOff   = Math.floor((toTs   - START_TS) / DAY);
  let iFrom = lastOnOrBefore(ser.d, fromOff - 1);
  let iTo   = lastOnOrBefore(ser.d, toOff);
  if (iFrom === -1 && iTo !== -1 && iTo > 0) iFrom = 0;
  if (iFrom !== -1 && iTo !== -1 && iFrom === iTo && iFrom > 0) iFrom = iTo - 1;
  if (iFrom === -1 || iTo === -1 || iTo <= iFrom) return null;
  const fp = ser.p[iFrom] / 100;
  const tp = ser.p[iTo]   / 100;
  if (!fp || !tp) return null;
  return {
    fromPrice: fp, toPrice: tp,
    changePercent: ((tp - fp) / fp) * 100,
    fromDate: new Date((START_TS + ser.d[iFrom] * DAY) * 1000).toISOString().slice(0, 10),
    toDate:   new Date((START_TS + ser.d[iTo]   * DAY) * 1000).toISOString().slice(0, 10),
  };
}

function parseCapital(s) {
  // Accept "1,00,000" or "100000" or "100,000"
  const cleaned = String(s).replace(/[^0-9.]/g, '');
  return parseFloat(cleaned) || 0;
}
function fmtINR(n) {
  // Indian numbering: 1,23,45,678
  const x = Math.round(n);
  const s = String(x);
  if (s.length <= 3) return s;
  const last3 = s.slice(-3);
  const rest = s.slice(0, -3);
  return rest.replace(/(\d)(?=(\d\d)+$)/g, '$1,') + ',' + last3;
}

async function runBacktest() {
  const screenFrom = document.getElementById('fromDate').value;
  const screenTo   = document.getElementById('toDate').value;
  const holdTo     = document.getElementById('backtestHoldTo').value;
  const topN       = Math.max(1, Math.min(500, parseInt(document.getElementById('backtestN').value, 10) || 10));
  const capital    = parseCapital(document.getElementById('backtestCapital').value);

  if (!screenFrom || !screenTo) return alert('Set the From/To dates in the main filter row first — those are the screening period.');
  if (!holdTo)                  return alert('Pick a Hold Until date.');
  if (new Date(screenTo) > new Date(holdTo)) return alert('Hold Until must be on or after the screening To Date.');
  if (capital <= 0)             return alert('Capital must be a positive number.');

  // The backtest screens over arbitrary history → ensure the full series is loaded first.
  if (!FULL_LOADED) {
    const btn = document.getElementById('runBacktestBtn'); const prev = btn.textContent;
    btn.textContent = 'Loading full history…'; btn.disabled = true;
    try { await ensureFull(); }
    catch (e) { alert('Could not load full history. Check your connection and retry.'); return; }
    finally { btn.textContent = prev; btn.disabled = false; }
  }

  const mcapBuckets   = getMcapBucketSet();
  const sectorFilter  = document.getElementById('sectorFilter').value;
  const indexFilter   = document.getElementById('indexFilter').value;

  // Build screen-period results filtered by index + F&O + mcap + sector. For
  // backtesting, mcap AND index/F&O membership MUST be evaluated as-of the
  // screening period (not today). Index membership comes from per-rebalance
  // snapshots walked back from today's NSE constituent lists. F&O uses
  // history if available, else today's NSE F&O list. Mcap is approximated as
  // today's mcap × (price-at-screen-From / latest-price). Yahoo's adjusted
  // prices handle splits/bonuses, so the main residual error is
  // buybacks/new-issuances (typically <10% for large caps).
  const fnoFilter = document.getElementById('fnoFilter').value;
  const historicalMembers = indexFilter !== 'all'
    ? getIndexMembersAt(indexFilter, screenFrom)
    : null;
  const fnoSet = fnoFilter === 'fno' ? getFnoMembersAt(screenFrom) : null;
  const screened = [];
  for (const ticker of UNIVERSE) {
    const m = META[ticker];
    if (indexFilter !== 'all') {
      // Use historical snapshot if available, else fall back to today's META.indices
      if (historicalMembers) {
        // ticker is "RELIANCE.NS" — strip suffix for lookup
        const base = ticker.endsWith('.NS') ? ticker.slice(0, -3) : ticker;
        if (!historicalMembers.has(base)) continue;
      } else {
        if (!(m.indices || []).includes(indexFilter)) continue;
      }
    }
    if (fnoSet) {
      const base = ticker.endsWith('.NS') ? ticker.slice(0, -3) : ticker;
      if (!fnoSet.has(base)) continue;
    }
    const indKey = (m.industry && m.industry.trim()) || m.sector || 'Uncategorized';
    if (sectorFilter !== 'all' && indKey !== sectorFilter) continue;
    const ser = SERIES[ticker];
    if (!ser || !ser.d.length || !m.mcap) continue;

    // Historical-mcap approximation, anchored at the screening From Date
    const latestPx = ser.p[ser.p.length - 1] / 100;
    const fromTs   = Math.floor(new Date(screenFrom + 'T00:00:00Z').getTime() / 1000);
    const fromOff  = Math.floor((fromTs - START_TS) / DAY);
    const iAtFrom  = lastOnOrBefore(ser.d, fromOff);
    if (iAtFrom === -1) continue;
    const pxAtFrom    = ser.p[iAtFrom] / 100;
    const histMcap    = latestPx > 0 ? m.mcap * (pxAtFrom / latestPx) : m.mcap;
    if (!inAnyMcapBucket(histMcap, mcapBuckets)) continue;

    const screen = computeReturn(ticker, screenFrom, screenTo);
    if (!screen) continue;
    // Need hold-period return too (from screening To Date → holdTo)
    const hold = computeReturn(ticker, screenTo, holdTo);
    if (!hold) continue;
    screened.push({
      ticker, symbol: m.symbol, name: m.name, sector: indKey,
      mcap: m.mcap, histMcap,
      screenPct: screen.changePercent,
      holdPct:   hold.changePercent,
      buyPrice:  hold.fromPrice,
      sellPrice: hold.toPrice,
      buyDate:   hold.fromDate,
      sellDate:  hold.toDate,
    });
  }
  if (screened.length === 0) {
    alert('No stocks matched both periods. Widen filters or date range.');
    return;
  }
  // Sort by screening return (desc) and take top-N
  screened.sort((a, b) => b.screenPct - a.screenPct);
  const picked = screened.slice(0, topN);

  // Equal-weight portfolio simulation
  const perStock = capital / picked.length;
  let finalValue = 0;
  for (const p of picked) {
    p.allocated  = perStock;
    p.finalValue = perStock * (1 + p.holdPct / 100);
    p.pnl        = p.finalValue - perStock;
    finalValue  += p.finalValue;
  }
  const totalReturnPct = (finalValue - capital) / capital * 100;
  const avgHoldPct     = picked.reduce((s, p) => s + p.holdPct, 0) / picked.length;
  const winners        = picked.filter(p => p.holdPct > 0).length;
  const top    = picked.reduce((a, b) => a.holdPct > b.holdPct ? a : b);
  const bottom = picked.reduce((a, b) => a.holdPct < b.holdPct ? a : b);

  renderBacktest({
    picked, capital, finalValue, totalReturnPct, avgHoldPct, winners,
    top, bottom,
    screenFrom: picked[0]?.buyDate ? null : screenFrom,    // not used here
    holdFrom: picked[0]?.buyDate, holdTo: picked[0]?.sellDate,
    universeSize: screened.length,
  });
}

function renderBacktest(d) {
  const wrap = document.getElementById('backtestResults');
  wrap.classList.remove('hidden');
  const sign = d.totalReturnPct >= 0 ? '+' : '';
  const retCls = d.totalReturnPct >= 0 ? 'text-green-700 bg-green-50' : 'text-red-700 bg-red-50';
  let rowsHtml = '';
  d.picked.forEach((p, i) => {
    const pnlCls = p.holdPct >= 0 ? 'chip-gain' : 'chip-loss';
    const sgn = p.holdPct >= 0 ? '+' : '';
    const screenSgn = p.screenPct >= 0 ? '+' : '';
    rowsHtml += '<tr class="hover:bg-slate-50">' +
      '<td class="px-3 py-2 text-slate-400 text-xs">' + (i + 1) + '</td>' +
      '<td class="px-3 py-2"><a href="./stock.html?sym=' + encodeURIComponent(p.symbol) + '" title="' + p.symbol + ' — full details" class="font-semibold text-slate-800 hover:text-blue-600 hover:underline">' + p.symbol + '</a></td>' +
      '<td class="px-3 py-2 text-slate-700 text-xs">' + p.name + '</td>' +
      '<td class="px-3 py-2 text-right text-slate-600 tabular-nums" title="Approx mcap at screening start (today\'s mcap × adj-price ratio)">&#8377;' + fmtINR(p.histMcap) + '</td>' +
      '<td class="px-3 py-2 text-right text-slate-600 tabular-nums">' + screenSgn + p.screenPct.toFixed(2) + '%</td>' +
      '<td class="px-3 py-2 text-right text-slate-600 tabular-nums">&#8377;' + p.buyPrice.toFixed(2) + '</td>' +
      '<td class="px-3 py-2 text-right text-slate-800 font-medium tabular-nums">&#8377;' + p.sellPrice.toFixed(2) + '</td>' +
      '<td class="px-3 py-2 text-right"><span class="inline-flex items-center gap-1 ' + pnlCls + ' rounded-md px-2 py-0.5 font-semibold text-xs tabular-nums">' + sgn + p.holdPct.toFixed(2) + '%</span></td>' +
      '<td class="px-3 py-2 text-right text-slate-600 tabular-nums">&#8377;' + fmtINR(p.allocated) + '</td>' +
      '<td class="px-3 py-2 text-right text-slate-800 font-medium tabular-nums">&#8377;' + fmtINR(p.finalValue) + '</td>' +
      '<td class="px-3 py-2 text-right tabular-nums ' + (p.pnl >= 0 ? 'text-green-700' : 'text-red-700') + '">' + (p.pnl >= 0 ? '+' : '') + '&#8377;' + fmtINR(p.pnl) + '</td>' +
      '</tr>';
  });
  const summary =
    '<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">' +
      '<div class="bg-slate-50 rounded-lg p-3 border border-slate-200">' +
        '<div class="text-[10px] uppercase tracking-wide font-semibold text-slate-500">Starting Capital</div>' +
        '<div class="text-base font-bold mt-0.5">&#8377;' + fmtINR(d.capital) + '</div>' +
      '</div>' +
      '<div class="bg-slate-50 rounded-lg p-3 border border-slate-200">' +
        '<div class="text-[10px] uppercase tracking-wide font-semibold text-slate-500">Final Value</div>' +
        '<div class="text-base font-bold mt-0.5">&#8377;' + fmtINR(d.finalValue) + '</div>' +
      '</div>' +
      '<div class="rounded-lg p-3 border border-slate-200 ' + retCls + '">' +
        '<div class="text-[10px] uppercase tracking-wide font-semibold opacity-80">Total Return</div>' +
        '<div class="text-base font-bold mt-0.5">' + sign + d.totalReturnPct.toFixed(2) + '%</div>' +
      '</div>' +
      '<div class="bg-slate-50 rounded-lg p-3 border border-slate-200">' +
        '<div class="text-[10px] uppercase tracking-wide font-semibold text-slate-500">Winners</div>' +
        '<div class="text-base font-bold mt-0.5">' + d.winners + ' / ' + d.picked.length + '</div>' +
      '</div>' +
      '<div class="bg-slate-50 rounded-lg p-3 border border-slate-200">' +
        '<div class="text-[10px] uppercase tracking-wide font-semibold text-slate-500">Hold Period</div>' +
        '<div class="text-xs font-bold mt-0.5">' + (d.holdFrom || '—') + ' &rarr; ' + (d.holdTo || '—') + '</div>' +
      '</div>' +
    '</div>' +
    '<div class="text-xs text-slate-500 mb-2">Top mover: <span class="font-semibold text-green-700"><a href="./stock.html?sym=' + encodeURIComponent(d.top.symbol) + '" class="hover:underline">' + d.top.symbol + '</a> +' + d.top.holdPct.toFixed(2) + '%</span> · ' +
      'Worst: <span class="font-semibold text-red-700"><a href="./stock.html?sym=' + encodeURIComponent(d.bottom.symbol) + '" class="hover:underline">' + d.bottom.symbol + '</a> ' + d.bottom.holdPct.toFixed(2) + '%</span> · ' +
      'Mean: ' + (d.avgHoldPct >= 0 ? '+' : '') + d.avgHoldPct.toFixed(2) + '% · ' +
      'Sampled from ' + d.universeSize.toLocaleString('en-IN') + ' stocks matching filters</div>';

  wrap.innerHTML = summary +
    '<div class="overflow-x-auto border border-slate-200 rounded-lg">' +
      '<table class="w-full text-sm">' +
        '<thead class="bg-slate-50 text-slate-600 text-xs uppercase">' +
        '<tr>' +
          '<th class="px-3 py-2 text-left font-semibold">#</th>' +
          '<th class="px-3 py-2 text-left font-semibold">Symbol</th>' +
          '<th class="px-3 py-2 text-left font-semibold">Company</th>' +
          '<th class="px-3 py-2 text-right font-semibold" title="Approx historical market cap at screening start">Hist Mcap<br><span class="normal-case text-slate-400 text-[10px] font-normal">(&#8377; Cr)</span></th>' +
          '<th class="px-3 py-2 text-right font-semibold">Screen %</th>' +
          '<th class="px-3 py-2 text-right font-semibold">Buy Price</th>' +
          '<th class="px-3 py-2 text-right font-semibold">Sell Price</th>' +
          '<th class="px-3 py-2 text-right font-semibold">Hold %</th>' +
          '<th class="px-3 py-2 text-right font-semibold">Allocated</th>' +
          '<th class="px-3 py-2 text-right font-semibold">Final Value</th>' +
          '<th class="px-3 py-2 text-right font-semibold">P&amp;L</th>' +
        '</tr></thead>' +
        '<tbody class="divide-y divide-slate-100">' + rowsHtml + '</tbody>' +
      '</table>' +
    '</div>';
  wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

document.getElementById('runBacktestBtn').addEventListener('click', runBacktest);
// Default Hold Until = today
(function initBacktest() {
  const today = new Date();
  document.getElementById('backtestHoldTo').value = today.toISOString().split('T')[0];
})();

// --- Market cap multi-select ---
const MCAP_LABELS = {
  'below100':    '\u2264 100 Cr',
  '100to500':    '100\u2013500 Cr',
  '500to1000':   '500\u20131k Cr',
  '1000to5000':  '1k\u20135k Cr',
  '5000to20000': '5k\u201320k Cr',
  'above20000':  '\u2265 20k Cr',
};
function getMcapBucketSet() {
  const cbs = document.querySelectorAll('#mcapPanel .mcap-cb:checked');
  return new Set(Array.from(cbs).map(c => c.dataset.bucket));
}
function updateMcapLabel() {
  const cbs = document.querySelectorAll('#mcapPanel .mcap-cb:checked');
  const lab = document.getElementById('mcapLabel');
  if (cbs.length === 0 || cbs.length >= 6) lab.textContent = 'All market caps';
  else if (cbs.length === 1)               lab.textContent = MCAP_LABELS[cbs[0].dataset.bucket];
  else if (cbs.length <= 3)                lab.textContent = Array.from(cbs).map(c => MCAP_LABELS[c.dataset.bucket]).join(', ');
  else                                      lab.textContent = cbs.length + ' selected';
}
document.getElementById('mcapTrigger').addEventListener('click', e => {
  e.stopPropagation();
  document.getElementById('mcapPanel').classList.toggle('hidden');
});
document.querySelectorAll('#mcapPanel .mcap-cb').forEach(cb =>
  cb.addEventListener('change', () => { updateMcapLabel(); if (lastResults.length || META) loadData(); }));
document.getElementById('mcapSelectAll').addEventListener('click', () => {
  document.querySelectorAll('#mcapPanel .mcap-cb').forEach(cb => cb.checked = true);
  updateMcapLabel();
  if (Object.keys(META).length) loadData();
});
document.getElementById('mcapClear').addEventListener('click', () => {
  document.querySelectorAll('#mcapPanel .mcap-cb').forEach(cb => cb.checked = false);
  updateMcapLabel();
  if (Object.keys(META).length) loadData();
});
// click outside closes the panel
document.addEventListener('click', e => {
  const panel = document.getElementById('mcapPanel');
  const trigger = document.getElementById('mcapTrigger');
  if (!panel.contains(e.target) && !trigger.contains(e.target)) panel.classList.add('hidden');
});
document.querySelectorAll('.preset-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const today = new Date();
    let from, to = today;
    if (btn.dataset.latest) {
      // Anchor to the snapshot date inside the data, not the calendar today,
      // so "Latest move" always points to the freshest trading-day pair the
      // dashboard actually contains (Yahoo close data lags reality).
      const snapDate = END_TS ? new Date(END_TS * 1000) : today;
      to   = snapDate;
      // From == To. With the new "from-anchor = last close before from-date"
      // rule, this resolves to (previous trading day's close → snapshot day's
      // close), i.e. exactly the latest 1-trading-day move. Slide-back picks
      // up the right pair even across weekends or holidays.
      from = snapDate;
    }
    else if (btn.dataset.ytd)             from = new Date(today.getFullYear(), 0, 1);
    else if (btn.dataset.since1996)       from = new Date(1996, 0, 1);
    else { const days = parseInt(btn.dataset.days, 10); from = new Date(); from.setDate(today.getDate() - days); }
    document.getElementById('toDate').value   = to.toISOString().split('T')[0];
    document.getElementById('fromDate').value = from.toISOString().split('T')[0];
  });
});

/* ---- "My screens": named saved filter-sets (localStorage sw_dash_presets, synced across
        devices through theme.js's settings sync when the browser is owner-unlocked) ---- */
function msAll() { try { return JSON.parse(localStorage.getItem('sw_dash_presets') || '[]'); } catch (e) { return []; } }
function msStore(a) {
  try { localStorage.setItem('sw_dash_presets', JSON.stringify(a)); } catch (e) {}
  if (window.swSync) try { swSync.pushSettings(); } catch (e) {}   // sync now, not just on page-leave
  msRender();
}
function msCapture() {
  return { from: document.getElementById('fromDate').value, to: document.getElementById('toDate').value,
           mcap: Array.from(document.querySelectorAll('.mcap-cb')).filter(c => c.checked).map(c => c.dataset.bucket),
           idx: document.getElementById('indexFilter').value, fno: document.getElementById('fnoFilter').value,
           sec: document.getElementById('sectorFilter').value };
}
function msApply(p) {
  if (p.from) document.getElementById('fromDate').value = p.from;
  if (p.to)   document.getElementById('toDate').value   = p.to;
  document.querySelectorAll('.mcap-cb').forEach(c => c.checked = (p.mcap || []).indexOf(c.dataset.bucket) >= 0);
  if (typeof updateMcapLabel === 'function') updateMcapLabel();
  document.getElementById('indexFilter').value  = p.idx || 'all';
  document.getElementById('fnoFilter').value    = p.fno || 'all';
  document.getElementById('sectorFilter').value = p.sec || 'all';
  loadData();
}
function msRender() {
  const list = msAll();
  document.getElementById('msList').innerHTML = list.map(function (p, i) {
    return '<span class="inline-flex items-center gap-1 text-xs bg-slate-100 hover:bg-indigo-100 text-slate-700 rounded-full pl-3 pr-1.5 py-1 font-medium cursor-pointer" data-ms="' + i + '" title="Apply this screen">' +
      p.name.replace(/&/g, '&amp;').replace(/</g, '&lt;') +
      '<button class="text-slate-400 hover:text-rose-600 font-bold px-0.5" data-msdel="' + i + '" title="Delete this screen">×</button></span>';
  }).join('') || '<span class="text-[11px] text-slate-400">none yet — set your filters, then save them here</span>';
}
document.getElementById('msSave').addEventListener('click', function () {
  const name = prompt('Name this screen (e.g. "Smallcap N500 momentum"):');
  if (!name || !name.trim()) return;
  const list = msAll().filter(function (p) { return p.name !== name.trim(); });
  list.unshift(Object.assign({ name: name.trim() }, msCapture()));
  msStore(list.slice(0, 30));
});
document.getElementById('msList').addEventListener('click', function (e) {
  const del = e.target.closest('[data-msdel]');
  if (del) { const l = msAll(); l.splice(+del.getAttribute('data-msdel'), 1); msStore(l); e.stopPropagation(); return; }
  const chip = e.target.closest('[data-ms]');
  if (chip) msApply(msAll()[+chip.getAttribute('data-ms')]);
});
msRender();
setTimeout(msRender, 2500);   // re-render once the settings sync may have pulled newer presets

loadAndInit();
</script>
</body>
</html>
"""

out = HTML.replace("__START_DATE__", start_date).replace("__GEN_DATE__", gen_date)
OUT_HTML.write_text(out, encoding="utf-8")
print(f"Wrote {OUT_HTML} ({OUT_HTML.stat().st_size / 1024 / 1024:.2f} MB)")

# Also emit the raw gzip payload as a standalone file for the stock-backtest page
# (it fetches + DecompressionStream-gunzips this instead of embedding 17 MB again).
stock_bin = OUT_HTML.parent / "stock_data.bin"
stock_bin.write_bytes(gz)
print(f"Wrote {stock_bin} ({len(gz) / 1024 / 1024:.2f} MB) for stock-backtest.html")
