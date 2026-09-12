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
"""Build the Mutual Funds dashboard — single-file HTML with all schemes embedded."""
import base64
import gzip
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "mutual_funds.json"
OUT = ROOT / "docs" / "mutual-funds.html"

mf = json.loads(SRC.read_text(encoding="utf-8"))
print(f"Building MF dashboard for {len(mf)} schemes...")

# ---------------------------------------------------------------------------
# Groww-style category normalization.
# Groww's screener (groww.in/mutual-funds/filter) groups funds into a small set
# of parent categories, each with SEBI subcategories. The raw `category` field
# from AMFI/mfapi is messy: clean SEBI names for open-ended funds, but garbage
# ("IDF", "Income", "1099 Days", "Growth") for closed-ended / FMP / defunct
# schemes that Groww does not list at all. We map every fund to a (group, sub)
# pair from Groww's taxonomy; anything that doesn't fit -> "Uncategorized".
# ---------------------------------------------------------------------------
import re as _re

GROUP_ORDER = ["Equity", "Hybrid", "Debt", "Index / Other", "Commodities", "Solution Oriented", "Uncategorized"]
SUB_ORDER = {
    "Equity": [
        "Large Cap",
        "Large & Mid Cap",
        "Mid Cap",
        "Small Cap",
        "Multi Cap",
        "Flexi Cap",
        "ELSS (Tax Saver)",
        "Sectoral / Thematic",
        "Focused",
        "Value",
        "Contra",
        "Dividend Yield",
    ],
    "Hybrid": [
        "Aggressive Hybrid",
        "Balanced Advantage",
        "Multi Asset Allocation",
        "Equity Savings",
        "Arbitrage",
        "Conservative Hybrid",
    ],
    "Debt": [
        "Overnight",
        "Liquid",
        "Ultra Short Duration",
        "Low Duration",
        "Money Market",
        "Short Duration",
        "Medium Duration",
        "Medium to Long Duration",
        "Long Duration",
        "Dynamic Bond",
        "Corporate Bond",
        "Credit Risk",
        "Banking & PSU",
        "Gilt",
        "Gilt 10Y Constant",
        "Floater",
    ],
    "Index / Other": ["Index Funds", "ETF", "Fund of Funds"],
    "Commodities": ["Gold", "Silver"],
    "Solution Oriented": ["Retirement", "Children's"],
    "Uncategorized": ["Uncategorized"],
}


def normalize_category(category, name=""):
    c = (category or "").lower()
    n = (name or "").lower()

    def has(*xs):
        return any(x in c for x in xs)

    # --- Equity ---
    if has("large & mid", "large and mid"):
        g, s = "Equity", "Large & Mid Cap"
    elif has("large cap"):
        g, s = "Equity", "Large Cap"
    elif has("mid cap"):
        g, s = "Equity", "Mid Cap"
    elif has("small cap"):
        g, s = "Equity", "Small Cap"
    elif has("multi cap", "multicap"):
        g, s = "Equity", "Multi Cap"
    elif has("flexi cap", "flexicap"):
        g, s = "Equity", "Flexi Cap"
    elif has("elss", "tax saver"):
        g, s = "Equity", "ELSS (Tax Saver)"
    elif has("sectoral", "thematic"):
        g, s = "Equity", "Sectoral / Thematic"
    elif has("focused"):
        g, s = "Equity", "Focused"
    elif has("dividend yield"):
        g, s = "Equity", "Dividend Yield"
    elif has("contra"):
        g, s = "Equity", "Contra"
    # --- Hybrid ---
    elif has("aggressive"):
        g, s = "Hybrid", "Aggressive Hybrid"
    elif has("balanced advantage", "dynamic asset"):
        g, s = "Hybrid", "Balanced Advantage"
    elif has("multi asset", "multi-asset"):
        g, s = "Hybrid", "Multi Asset Allocation"
    elif has("equity savings"):
        g, s = "Hybrid", "Equity Savings"
    elif has("arbitrage"):
        g, s = "Hybrid", "Arbitrage"
    elif has("conservative"):
        g, s = "Hybrid", "Conservative Hybrid"
    # --- Debt ---
    elif has("overnight"):
        g, s = "Debt", "Overnight"
    elif has("liquid"):
        g, s = "Debt", "Liquid"
    elif has("ultra short"):
        g, s = "Debt", "Ultra Short Duration"
    elif has("low duration"):
        g, s = "Debt", "Low Duration"
    elif has("money market"):
        g, s = "Debt", "Money Market"
    elif has("short duration"):
        g, s = "Debt", "Short Duration"
    elif has("medium to long", "medium-long"):
        g, s = "Debt", "Medium to Long Duration"
    elif has("medium duration"):
        g, s = "Debt", "Medium Duration"
    elif has("long duration"):
        g, s = "Debt", "Long Duration"
    elif has("dynamic bond"):
        g, s = "Debt", "Dynamic Bond"
    elif has("corporate bond"):
        g, s = "Debt", "Corporate Bond"
    elif has("credit risk"):
        g, s = "Debt", "Credit Risk"
    elif has("banking"):
        g, s = "Debt", "Banking & PSU"
    elif has("10 year constant", "10y constant"):
        g, s = "Debt", "Gilt 10Y Constant"
    elif has("gilt"):
        g, s = "Debt", "Gilt"
    elif has("floater", "floating rate"):
        g, s = "Debt", "Floater"
    elif has("value"):
        g, s = "Equity", "Value"  # after the specific ones
    # --- Index / Other ---
    elif has("index"):
        g, s = "Index / Other", "Index Funds"
    elif has("etf"):
        g, s = "Index / Other", "ETF"
    elif has("fof", "fund of fund"):
        g, s = "Index / Other", "Fund of Funds"
    # --- Solution Oriented ---
    elif has("retirement"):
        g, s = "Solution Oriented", "Retirement"
    elif has("children", "child"):
        g, s = "Solution Oriented", "Children's"
    else:
        g, s = "Uncategorized", "Uncategorized"
    # Commodities are identified by fund name (Gold/Silver ETFs & FoFs), which
    # otherwise land in Index / Other or Uncategorized.
    if g in ("Index / Other", "Uncategorized"):
        if _re.search(r"\bgold\b", n):
            g, s = "Commodities", "Gold"
        elif _re.search(r"\bsilver\b", n):
            g, s = "Commodities", "Silver"
    return g, s


from collections import Counter as _Counter

_dist = _Counter()
for r in mf:
    g, s = normalize_category(r.get("category", ""), r.get("name", ""))
    r["g"], r["s"] = g, s
    r.pop("cat", None)  # drop the old messy short-category field
    _dist[g] += 1
print("  Category groups: " + ", ".join(f"{g}={_dist[g]}" for g in GROUP_ORDER if _dist[g]))

raw = json.dumps(mf, separators=(",", ":")).encode()
gz = gzip.compress(raw, compresslevel=9)
b64 = base64.b64encode(gz).decode()
print(f"  Raw {len(raw) / 1024:.1f} KB → gzip {len(gz) / 1024:.1f} KB → b64 {len(b64) / 1024:.1f} KB")


# ---------------------------------------------------------------------------
# Daily NAV history for the exact-date calculator. fetch_mf_returns.py already
# builds the compact payload (shared YYYYMMDD axis + per-fund [startIdx, delta-
# encoded paise]) and writes it pre-gzipped+base64 to scripts/mf_history.b64.
# We just embed it. If absent (build without a fresh fetch), the date filter is
# disabled.
# ---------------------------------------------------------------------------
def _ymd(n):
    s = str(n)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


HISTSRC = ROOT / "scripts" / "mf_history.b64"
if HISTSRC.exists():
    hist_b64 = HISTSRC.read_text(encoding="utf-8").strip()
    # Write the daily NAV history as an EXTERNAL gzip file. The page lazy-loads it only when the
    # custom-date calculator or a fund-detail modal needs it — instead of base64-inlining ~10 MB
    # into the HTML, which forced every first-time visitor to download it all up front.
    hist_gz = base64.b64decode(hist_b64)
    (OUT.parent / "mf_history.bin").write_bytes(hist_gz)
    print(f"  History: wrote external mf_history.bin ({len(hist_gz) / 1024 / 1024:.1f} MB, lazy-loaded)")
    # The page needs the covered date span up front to bound the date pickers, but the history
    # itself only loads on first use — so bake the span in here rather than after the fetch.
    _hd = json.loads(gzip.decompress(hist_gz))["dates"]
    hist_lo, hist_hi = _ymd(_hd[0]), _ymd(_hd[-1])
    del _hd
    print(f"  History: covers {hist_lo} → {hist_hi}")
else:
    hist_lo = hist_hi = ""
    print("  History: scripts/mf_history.b64 not found — custom date filter disabled")

gen = datetime.now().strftime("%d %b %Y %H:%M")

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>STOCKSWORLD · Mutual Funds</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="./theme.css" />
<script src="./theme.js"></script>
<style>
  table { font-feature-settings: "tnum" 1; }
  table thead th { position:sticky; top:0; background:#f8fafc; z-index:10; }
  .badge { display:inline-block; padding:1px 6px; border-radius:9999px; font-size:10px; font-weight:600; }
  .b-equity { background:#dbeafe; color:#1e40af; }
  .b-debt   { background:#fef3c7; color:#92400e; }
  .b-hybrid { background:#fae8ff; color:#86198f; }
  .b-passive{ background:#dcfce7; color:#166534; }
  .b-fof    { background:#e0e7ff; color:#3730a3; }
  .b-commodity { background:#ffedd5; color:#9a3412; }
  .b-other  { background:#f1f5f9; color:#475569; }
  .b-plan-dir { background:#dbeafe; color:#1e40af; }
  .b-plan-reg { background:#fee2e2; color:#991b1b; }
  #loadingOverlay{position:fixed;inset:0;background:#f8fafc;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:50;}
  .pos { color:#15803d; font-weight:600; }
  .neg { color:#b91c1c; font-weight:600; }
</style>
</head>
<body class="bg-slate-50 min-h-screen text-slate-800">

<div id="loadingOverlay">
  <div class="w-10 h-10 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin mb-3"></div>
  <p class="text-sm text-slate-600" id="statusText">Loading mutual funds…</p>
</div>

<header class="sticky top-0 z-40 bg-white/90 backdrop-blur-md border-b border-slate-200 shadow-sm">
  <div class="max-w-screen-2xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
    <a href="./index.html" class="flex items-center gap-2.5 shrink-0 group">
      <span class="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-600 text-white flex items-center justify-center font-extrabold text-[13px] shadow-md group-hover:scale-105 transition">SW</span>
      <span class="font-bold text-slate-900 tracking-tight hidden sm:block">STOCKS<span class="text-indigo-600">WORLD</span></span>
    </a>
    <div class="flex items-center gap-3 min-w-0">
      <nav></nav>
      <a href="./backtest.html" class="hidden md:inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 transition whitespace-nowrap">📈 Backtest</a>
      <span class="text-[11px] text-slate-400 hidden xl:block shrink-0">Snapshot &middot; __GEN__</span>
    </div>
  </div>
</header>

<main class="max-w-screen-2xl mx-auto px-4 py-6">
  <!-- Filter bar -->
  <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-200 mb-4">
    <div class="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">Search by name / AMC</label>
        <input type="search" id="searchBox" placeholder="e.g. Parag Parikh, Small Cap, HDFC…"
               class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500"/>
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">Plan</label>
        <select id="planFilter" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 bg-white">
          <option value="Direct" selected>Direct only</option>
          <option value="Regular">Regular only</option>
          <option value="all">Both (Direct + Regular)</option>
        </select>
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">Category</label>
        <select id="catFilter" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 bg-white">
          <option value="all">All categories</option>
        </select>
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">Min. years since inception</label>
        <select id="yrFilter" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 bg-white">
          <option value="0" selected>Any</option>
          <option value="1">1 year+</option>
          <option value="3">3 years+</option>
          <option value="5">5 years+</option>
          <option value="10">10 years+</option>
        </select>
      </div>
      <div class="text-right">
        <button id="resetBtn" class="text-sm text-slate-600 hover:text-blue-600">Reset filters</button>
      </div>
    </div>
    <div class="mt-3 pt-3 border-t border-slate-100 flex flex-wrap items-end gap-3">
      <div class="text-xs font-semibold text-amber-700 pb-2">&#128197; Custom return window:</div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">From (date)</label>
        <input type="date" id="fromDate" min="__HIST_LO__" max="__HIST_HI__" class="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-amber-500"/>
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">To (date)</label>
        <input type="date" id="toDate" min="__HIST_LO__" max="__HIST_HI__" class="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-amber-500"/>
      </div>
      <div>
        <label class="block text-xs font-medium text-slate-600 mb-1">Show as</label>
        <select id="custMode" class="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-amber-500 bg-white">
          <option value="abs" selected>Absolute</option>
          <option value="cagr">Annualized (CAGR)</option>
        </select>
      </div>
      <button id="clearDates" class="text-sm text-slate-600 hover:text-amber-600 pb-2">Clear</button>
      <div id="rangeInfo" class="text-xs text-slate-500 pb-2"></div>
      <div id="custWarn" class="hidden basis-full text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2"></div>
    </div>
  </div>

  <!-- Stats -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4" id="statsBar">
    <div class="bg-white p-3 rounded-xl shadow-sm border border-slate-200">
      <div class="text-[11px] text-slate-500 uppercase">Showing</div>
      <div class="text-lg font-bold" id="statShown">—</div>
    </div>
    <div class="bg-white p-3 rounded-xl shadow-sm border border-slate-200">
      <div class="text-[11px] text-slate-500 uppercase">Categories</div>
      <div class="text-lg font-bold" id="statCats">—</div>
    </div>
    <div class="bg-white p-3 rounded-xl shadow-sm border border-slate-200">
      <div class="text-[11px] text-slate-500 uppercase">Avg CAGR (shown)</div>
      <div class="text-lg font-bold" id="statCagr">—</div>
    </div>
    <div class="bg-white p-3 rounded-xl shadow-sm border border-slate-200">
      <div class="text-[11px] text-slate-500 uppercase">Best returner (shown)</div>
      <div class="text-sm font-bold truncate" id="statBest" title="">—</div>
    </div>
  </div>

  <!-- Results -->
  <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
    <div class="overflow-x-auto max-h-[calc(100vh-280px)] overflow-y-auto">
      <table class="w-full text-xs">
        <thead class="text-[10px] uppercase text-slate-600 border-b border-slate-200">
          <tr>
            <th class="px-2 py-2 text-left font-semibold w-10">#</th>
            <th class="px-3 py-2 text-left font-semibold cursor-pointer hover:bg-slate-100 select-none min-w-[260px]" data-sort="short">Mutual fund <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="aum">AUM<br><span class="normal-case text-slate-400 text-[9px] font-normal">(soon)</span></th>
            <th class="px-2 py-2 text-left font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="s">Category <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none" data-sort="years">Yrs <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none border-l border-slate-200 bg-slate-50" data-sort="r1d">1D <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none bg-slate-50" data-sort="r1w">1W <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none bg-slate-50" data-sort="r1m">1M <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none bg-slate-50" data-sort="r3m">3M <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none bg-slate-50" data-sort="r6m">6M <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none bg-slate-50" data-sort="r1y">1Y <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none border-l border-slate-200 bg-blue-50" data-sort="r3y">3Y* <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none bg-blue-50" data-sort="r5y">5Y* <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none bg-blue-50" data-sort="r10y">10Y* <span class="sort-ind text-slate-300">&#8597;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none border-l border-slate-200 bg-blue-100" data-sort="cagrPct"><b>Since incep*</b> <span class="sort-ind text-blue-600">&#9660;</span></th>
            <th class="px-2 py-2 text-right font-semibold cursor-pointer hover:bg-slate-100 select-none border-l-2 border-amber-300 bg-amber-100" data-sort="cust" id="custHdr">Custom <span class="sort-ind text-slate-300">&#8597;</span></th>
          </tr>
          <tr class="text-[9px] normal-case text-slate-400">
            <th class="px-2 py-1"></th>
            <th class="px-3 py-1 text-left">name &middot; AMC</th>
            <th class="px-2 py-1 text-right">₹ Cr</th>
            <th class="px-2 py-1"></th>
            <th class="px-2 py-1 text-right">since launch</th>
            <th colspan="6" class="px-2 py-1 text-center bg-slate-50 border-l border-slate-200">absolute % returns</th>
            <th colspan="4" class="px-2 py-1 text-center bg-blue-50 border-l border-slate-200">annualized (CAGR) %</th>
            <th class="px-2 py-1 text-right bg-amber-50 border-l-2 border-amber-300" id="custSub">set dates</th>
          </tr>
        </thead>
        <tbody id="resultsBody"></tbody>
      </table>
    </div>
  </div>
  <p class="text-[11px] text-slate-500 mt-3">
    * Columns marked with asterisk are annualized (CAGR). 1D–1Y are absolute returns.
    Data sources: AMFI NAVAll daily file (scheme master + current NAV) and mfapi.in (full NAV history).
    Growth plans only (no IDCW/dividend options), tagged <span class="badge b-plan-dir">DIR</span> /
    <span class="badge b-plan-reg">REG</span>. <b>Data floor:</b> Direct-plan NAV history starts Jan 2013
    (when direct plans were introduced); Regular-plan history starts Apr 2006 (AMFI's daily-NAV archive
    floor). So a fund older than 2006 shows max ~20 years even on its Regular plan — its true 1990s/2000s
    launch isn't available in free data. "Since inception" means since that data floor, not the fund's legal launch.
    AUM is a placeholder for now — AMFI's scheme-wise AUM is published as a monthly XLSX and will be ingested separately.
    Returns shown as "—" mean the fund hasn't existed for that lookback period (e.g. no 10Y return for a 6-year-old fund).
    Side-pocket / Segregated schemes show -100% returns by design.
    Categories follow Groww's taxonomy (parent group &rarr; subcategory). Closed-ended,
    fixed-maturity (FMP), infrastructure-debt and other schemes Groww doesn't list are grouped under <b>Uncategorized</b>.
  </p>
</main>

<!-- Per-fund detail modal -->
<div id="detailModal" class="hidden fixed inset-0 z-50 bg-black/40 flex items-start justify-center overflow-y-auto p-3">
  <div class="bg-white rounded-xl shadow-xl max-w-4xl w-full my-6" onclick="event.stopPropagation()">
    <div class="flex items-center justify-between gap-3 px-5 py-3 border-b border-slate-200 sticky top-0 bg-white rounded-t-xl">
      <div id="detTitle" class="font-bold text-slate-900 text-sm md:text-base truncate"></div>
      <div class="flex items-center gap-3 shrink-0">
        <label class="text-xs text-slate-500">Window
          <select id="detWin" class="border border-slate-300 rounded px-2 py-1 text-sm ml-1"><option>3</option><option selected>5</option><option>7</option><option>10</option></select> yrs</label>
        <button id="detClose" class="text-slate-400 hover:text-red-600 text-2xl leading-none">&times;</button>
      </div>
    </div>
    <div id="detSummary" class="px-5 pt-3 text-xs text-slate-500"></div>
    <div id="detTables" class="px-5 pb-5"></div>
  </div>
</div>

<script id="compressedData" type="application/octet-stream">__B64__</script>
<script>
'use strict';
let ALL = [];
let BYCODE = {};
let SHOWN = [];
let SORT = { key: 'cagrPct', dir: -1 };
let HIST = null;            // {months:[...], idx:{m:i}, data:{code:[startIdx, nav...]}}
let FROM = null, TO = null; // active custom return window (YYYY-MM strings)

async function loadData() {
  const statusEl = document.getElementById('statusText');
  statusEl.textContent = 'Decoding…';
  const b64 = document.getElementById('compressedData').textContent.replace(/\s+/g,'');
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  const text = await new Response(stream).text();
  ALL = JSON.parse(text);
  ALL.forEach(r => { BYCODE[r.code] = r; });
  document.getElementById('compressedData').remove();

  // The daily NAV history (custom-date calculator + fund-detail calendars) is a separate ~7 MB
  // file fetched lazily by ensureHistory() on first use — NOT loaded here — so the page paints
  // instantly. The custom column stays visible; using it (or opening a fund) triggers the fetch.

  // Build the two-level category dropdown (Groww-style: parent group -> subcategory)
  const GROUP_ORDER = ['Equity','Hybrid','Debt','Index / Other','Commodities','Solution Oriented','Uncategorized'];
  const SUB_ORDER = {
    'Equity': ['Large Cap','Large & Mid Cap','Mid Cap','Small Cap','Multi Cap','Flexi Cap','ELSS (Tax Saver)','Sectoral / Thematic','Focused','Value','Contra','Dividend Yield'],
    'Hybrid': ['Aggressive Hybrid','Balanced Advantage','Multi Asset Allocation','Equity Savings','Arbitrage','Conservative Hybrid'],
    'Debt': ['Overnight','Liquid','Ultra Short Duration','Low Duration','Money Market','Short Duration','Medium Duration','Medium to Long Duration','Long Duration','Dynamic Bond','Corporate Bond','Credit Risk','Banking & PSU','Gilt','Gilt 10Y Constant','Floater'],
    'Index / Other': ['Index Funds','ETF','Fund of Funds'],
    'Commodities': ['Gold','Silver'],
    'Solution Oriented': ['Retirement',"Children's"],
    'Uncategorized': ['Uncategorized'],
  };
  const gCount = {}, sCount = {};
  for (const r of ALL) {
    gCount[r.g] = (gCount[r.g] || 0) + 1;
    (sCount[r.g] = sCount[r.g] || {});
    sCount[r.g][r.s] = (sCount[r.g][r.s] || 0) + 1;
  }
  const sel = document.getElementById('catFilter');
  GROUP_ORDER.forEach(g => {
    if (!gCount[g]) return;
    const og = document.createElement('optgroup');
    og.label = g + '  (' + gCount[g] + ')';
    const allOpt = document.createElement('option');
    allOpt.value = 'G:::' + g;
    allOpt.textContent = 'All ' + g + '  (' + gCount[g] + ')';
    og.appendChild(allOpt);
    const subs = (SUB_ORDER[g] || []).slice();
    Object.keys(sCount[g] || {}).forEach(s => { if (!subs.includes(s)) subs.push(s); });
    subs.forEach(s => {
      if (!sCount[g] || !sCount[g][s]) return;
      const opt = document.createElement('option');
      opt.value = 'S:::' + g + ':::' + s;
      opt.textContent = ' ' + s + '  (' + sCount[g][s] + ')';
      og.appendChild(opt);
    });
    sel.appendChild(og);
  });

  document.getElementById('loadingOverlay').remove();
  render();
}

// ---- Exact-date return helpers ---------------------------------------------
function ymdToInt(s) { return parseInt(s.replace(/-/g, ''), 10); }      // "2020-03-23"->20200323
function intToYmd(n) { const s = '' + n; return s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8); }
function ymdToDate(n) { const s = '' + n; return new Date(+s.slice(0,4), +s.slice(4,6) - 1, +s.slice(6,8)); }

// nearest trading day on/before target (binary search the shared date axis).
// A target before the axis starts clamps to the first day rather than failing: otherwise every
// NAV lookup returns null and the whole Custom column blanks out.
function dateToIdx(ymd) {
  const A = HIST.dates;
  if (ymd <= A[0]) return 0;
  if (ymd >= A[A.length - 1]) return A.length - 1;
  let lo = 0, hi = A.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (A[mid] <= ymd) lo = mid; else hi = mid - 1; }
  return lo;
}
// decode a fund's delta-paise array into a cumulative Int32Array (cached); frees the raw array
function decoded(code) {
  let d = HIST.dec[code];
  if (d) return d;
  const a = HIST.data[code];
  if (!a) return null;
  const start = a[0], n = a.length - 1, out = new Int32Array(n);
  let acc = 0;
  for (let i = 0; i < n; i++) { acc += a[i + 1]; out[i] = acc; }
  d = { start: start, nav: out };
  HIST.dec[code] = d; HIST.data[code] = null;   // free raw to save memory
  return d;
}
function navAtIdx(code, gi) {           // NAV (paise) of fund `code` at axis index gi
  const d = decoded(code);
  if (!d) return null;
  const k = gi - d.start;
  if (k < 0 || k >= d.nav.length) return null;
  return d.nav[k];
}
// Most funds post NAV a day or two behind the newest fund on the shared axis, so an exact-day
// lookup at the To end blanks nearly every row. Fall back to the fund's latest NAV within
// `back` axis days; beyond that the fund is genuinely dead/dormant and null is right.
function navAtOrBefore(code, gi, back) {
  const d = decoded(code);
  if (!d) return null;
  const last = d.start + d.nav.length - 1;
  const g = Math.min(gi, last);
  if (g < d.start || gi - g > (back || 0)) return null;
  return d.nav[g - d.start];
}

// ---- per-fund detail: monthly / trailing / forward return calendars ----
function fundRange(code){ const d=decoded(code); if(!d) return null; return [HIST.dates[d.start], HIST.dates[d.start+d.nav.length-1]]; }
function addYM(Y,M,n){ M+=n; while(M>12){M-=12;Y++;} while(M<1){M+=12;Y--;} return [Y,M]; }
function meNavC(code,Y,M){ const idx=dateToIdx(Y*10000+M*100+31); const dd=HIST.dates[idx]; return (Math.floor(dd/10000)===Y && Math.floor(dd/100)%100===M) ? navAtIdx(code,idx) : null; }
const MN_=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function _cell(v,b){ return v==null ? '<td class="px-1 py-0.5 text-right text-slate-300">·</td>'
  : '<td class="px-1 py-0.5 text-right '+(b?'font-semibold border-l border-slate-200 ':'')+(v>=0?'pos':'neg')+'">'+(v>=0?'+':'')+v.toFixed(1)+'</td>'; }
function calMonthly(code){
  const r=fundRange(code); if(!r) return ''; const fy=Math.floor(r[0]/10000), ly=Math.floor(r[1]/10000);
  let rows='';
  for(let Y=fy;Y<=ly;Y++){
    let cells='', yf=1, any=false;
    for(let m=1;m<=12;m++){
      const cur=meNavC(code,Y,m), prev=m===1?meNavC(code,Y-1,12):meNavC(code,Y,m-1);
      if(cur==null||prev==null||prev<=0){cells+=_cell(null);continue;}
      const ret=(cur/prev-1)*100; yf*=(1+ret/100); any=true; cells+=_cell(ret);
    }
    rows+='<tr class="border-t border-slate-50"><td class="px-1 py-0.5 font-medium text-slate-600">'+Y+'</td>'+cells+_cell(any?(yf-1)*100:null,true)+'</tr>';
  }
  const head='<th class="px-1 py-1 text-left">Year</th>'+MN_.map(m=>'<th class="px-1 py-1 text-right">'+m+'</th>').join('')+'<th class="px-1 py-1 text-right border-l border-slate-200">Year</th>';
  return '<div class="overflow-x-auto"><table class="text-[11px] w-full"><thead class="text-[10px] uppercase text-slate-500"><tr>'+head+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
}
function calRolling(code,win,fwd){
  const r=fundRange(code); if(!r) return ''; const fy=Math.floor(r[0]/10000), ly=Math.floor(r[1]/10000);
  let rows='', any=false;
  for(let Y=fy;Y<=ly;Y++){
    let cells='', rowHas=false;
    for(let m=1;m<=12;m++){
      const a = fwd ? meNavC(code,Y,m) : meNavC(code,Y-win,m);
      const b = fwd ? meNavC(code,Y+win,m) : meNavC(code,Y,m);
      if(a==null||b==null||a<=0){cells+=_cell(null);continue;}
      cells+=_cell((Math.pow(b/a,1/win)-1)*100); rowHas=true; any=true;
    }
    if(rowHas) rows+='<tr class="border-t border-slate-50"><td class="px-1 py-0.5 font-medium text-slate-600">'+Y+'</td>'+cells+'</tr>';
  }
  if(!any) return '<div class="text-xs text-slate-400 py-2">Not enough history for '+win+'-year windows.</div>';
  const head='<th class="px-1 py-1 text-left">'+(fwd?'Invest in':'As of')+'</th>'+MN_.map(m=>'<th class="px-1 py-1 text-right">'+m+'</th>').join('');
  return '<div class="overflow-x-auto"><table class="text-[11px] w-full"><thead class="text-[10px] uppercase text-slate-500"><tr>'+head+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
}
// Lazily fetch the ~7 MB daily NAV history — only when the custom-date calculator or a
// fund-detail modal first needs it. Cached after the first fetch.
let __histLoading = null;
async function ensureHistory() {
  if (HIST) return true;
  if (!__histLoading) __histLoading = (async () => {
    const buf = await (await fetch('./mf_history.bin')).arrayBuffer();
    const stream = new Blob([new Uint8Array(buf)]).stream().pipeThrough(new DecompressionStream('gzip'));
    HIST = JSON.parse(await new Response(stream).text());   // {dates:[YYYYMMDD], data:{code:[startIdx, delta-paise...]}}
    HIST.dec = {};
    const fd = document.getElementById('fromDate'), td = document.getElementById('toDate');
    if (fd && td && HIST.dates && HIST.dates.length) {
      const lo = intToYmd(HIST.dates[0]), hi = intToYmd(HIST.dates[HIST.dates.length - 1]);
      fd.min = td.min = lo; fd.max = td.max = hi;
    }
  })().catch(e => { __histLoading = null; HIST = null; });
  await __histLoading;
  return !!HIST;
}
let DETAIL_CODE = null;
async function showFundDetail(code){
  const r=BYCODE[code]; if(!r) return; DETAIL_CODE=code;
  const planTag = (r.plan||'Direct')==='Regular' ? '<span class="badge b-plan-reg">REG</span>' : '<span class="badge b-plan-dir">DIR</span>';
  document.getElementById('detTitle').innerHTML = cleanName(r.short).replace(/[<>]/g,'') + ' ' + planTag;
  document.getElementById('detSummary').innerHTML =
    '<span class="badge '+badgeClass(r.g)+'">'+r.s+'</span> · '+(r.amc||'').replace(/[<>]/g,'')+
    ' · since-incep CAGR <b>'+(r.cagrPct>=0?'+':'')+r.cagrPct.toFixed(1)+'%</b>'+
    ' · 1Y '+fmtRet(r.r1y)+' · 3Y '+fmtRet(r.r3y)+' · 5Y '+fmtRet(r.r5y)+' · '+r.years.toFixed(1)+'y of data';
  document.getElementById('detailModal').classList.remove('hidden');
  document.body.style.overflow='hidden';
  if (!HIST) {
    document.getElementById('detTables').innerHTML = '<div class="text-sm text-slate-500 py-6 text-center">Loading price history…</div>';
    if (!await ensureHistory()) { document.getElementById('detTables').innerHTML = '<div class="text-sm text-red-500 py-6 text-center">Couldn’t load price history. Check your connection and retry.</div>'; return; }
    if (DETAIL_CODE !== code) return;   // user closed/switched while it loaded
  }
  renderDetail();
}
function renderDetail(){
  const code=DETAIL_CODE; if(code==null) return;
  const win=+document.getElementById('detWin').value;
  document.getElementById('detTables').innerHTML =
    '<div class="text-sm font-bold text-slate-800 mt-4 mb-1">📅 Monthly returns — each calendar month&apos;s gain</div>'+calMonthly(code)+
    '<div class="text-sm font-bold text-slate-800 mt-5 mb-1">📉 Trailing '+win+'-year return — your '+win+'-year CAGR as of each month</div>'+calRolling(code,win,false)+
    '<div class="text-sm font-bold text-slate-800 mt-5 mb-1">📈 Forward '+win+'-year return — invest at month-start &amp; hold '+win+' years</div>'+calRolling(code,win,true)+
    '<div class="text-[10px] text-slate-400 mt-2">Monthly = each month&apos;s NAV return (right "Year" col = calendar-year return). Trailing = '+win+'-yr CAGR ending that month. Forward = '+win+'-yr CAGR if you invested that month. "·" = outside the fund&apos;s data window.</div>';
}
function closeFundDetail(){ document.getElementById('detailModal').classList.add('hidden'); document.body.style.overflow=''; DETAIL_CODE=null; }
function recomputeCust() {
  const f = document.getElementById('fromDate').value;
  const t = document.getElementById('toDate').value;
  const info = document.getElementById('rangeInfo');
  const sub  = document.getElementById('custSub');
  if (!HIST || !f || !t || f >= t) {
    FROM = TO = null;
    for (const r of ALL) r.cust = null;
    if (sub) sub.textContent = 'set dates';
    info.textContent = (f && t && f >= t) ? 'From must be before To' : '';
    return;
  }
  FROM = f; TO = t;
  const mode = document.getElementById('custMode').value;   // 'abs' | 'cagr'
  const fi = dateToIdx(ymdToInt(f)), ti = dateToIdx(ymdToInt(t));
  // actual elapsed years between the matched trading days
  const yf = (ymdToDate(HIST.dates[ti]) - ymdToDate(HIST.dates[fi])) / (365.25 * 86400000);
  const useCagr = (mode === 'cagr' && yf >= 1);   // don't annualize sub-1-year windows
  let n = 0;
  for (const r of ALL) {
    const nf = navAtIdx(r.code, fi), nt = navAtOrBefore(r.code, ti, 10);  // paise; ratio cancels /100
    if (nf != null && nt != null && nf > 0) {
      r.cust = useCagr ? (Math.pow(nt / nf, 1 / yf) - 1) * 100 : (nt - nf) / nf * 100;
      n++;
    } else r.cust = null;
  }
  // dateToIdx clamps to the axis, so say so when the window asked for more than we hold
  const af = intToYmd(HIST.dates[fi]), at = intToYmd(HIST.dates[ti]);
  const clipped = (ymdToInt(f) < HIST.dates[0]) || (ymdToInt(t) > HIST.dates[HIST.dates.length - 1]);
  if (sub) sub.textContent = af + ' → ' + at + (useCagr ? ' · CAGR' : ' · abs');
  info.textContent = n.toLocaleString() + ' funds · '
    + (useCagr ? 'annualized CAGR over ' + yf.toFixed(1) + 'y'
               : 'absolute % over the window' + (mode === 'cagr' ? ' (<1y, not annualized)' : ''))
    + (clipped ? ' · window clipped to available NAV data (' + af + ' → ' + at + ')' : '');
}

function badgeClass(g) {
  switch (g) {
    case 'Equity':            return 'b-equity';
    case 'Debt':              return 'b-debt';
    case 'Hybrid':            return 'b-hybrid';
    case 'Index / Other':     return 'b-passive';
    case 'Commodities':       return 'b-commodity';
    case 'Solution Oriented': return 'b-fof';
    default:                  return 'b-other';
  }
}

function fmtINR(n) {
  if (n == null || isNaN(n)) return '—';
  return n.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

function cleanName(s) {
  return (s || '')
    .replace(/\s*[-–]\s*(Regular|Direct)(\s*Plan)?(\s*[-–]?\s*Growth(\s*Option)?)?\s*$/i, '')
    .replace(/\s*[-–]\s*Growth(\s*Option|\s*Plan)?\s*$/i, '')
    .replace(/\s*[-–]\s*$/, '')
    .trim();
}

function applyFilters() {
  const q     = document.getElementById('searchBox').value.trim().toLowerCase();
  const cat   = document.getElementById('catFilter').value;
  const plan  = document.getElementById('planFilter').value;
  const minYr = parseFloat(document.getElementById('yrFilter').value) || 0;
  let s = ALL.filter(r => {
    if (plan !== 'all' && (r.plan || 'Direct') !== plan) return false;
    if (cat !== 'all') {
      if (cat.startsWith('G:::')) {
        if (r.g !== cat.slice(4)) return false;
      } else if (cat.startsWith('S:::')) {
        const rest = cat.slice(4), i = rest.indexOf(':::');
        if (r.g !== rest.slice(0, i) || r.s !== rest.slice(i + 3)) return false;
      }
    }
    if (r.years < minYr) return false;
    if (q) {
      const hay = (r.short + ' ' + (r.amc || '') + ' ' + r.name).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  // Apply sort — push nulls to the bottom regardless of direction
  const dir = SORT.dir;
  s.sort((a, b) => {
    const va = a[SORT.key], vb = b[SORT.key];
    const aN = (va === null || va === undefined);
    const bN = (vb === null || vb === undefined);
    if (aN && bN) return 0;
    if (aN) return 1;
    if (bN) return -1;
    if (typeof va === 'string') return dir === -1 ? vb.localeCompare(va) : va.localeCompare(vb);
    return (vb - va) * (dir === -1 ? 1 : -1);
  });
  SHOWN = s;
}

function fmtRet(v) {
  if (v == null) return '<span class="text-slate-300">—</span>';
  const cls = v >= 0 ? 'pos' : 'neg';
  const sign = v >= 0 ? '+' : '';
  return '<span class="' + cls + '">' + sign + v.toFixed(1) + '</span>';
}

function render() {
  applyFilters();
  const tbody = document.getElementById('resultsBody');
  tbody.innerHTML = '';
  const frag = document.createDocumentFragment();
  // Limit rendered rows to first 1500 for speed
  const slice = SHOWN.slice(0, 1500);
  slice.forEach((r, i) => {
    const tr = document.createElement('tr');
    tr.className = i % 2 ? 'bg-slate-50' : '';
    const cagr = r.cagrPct;
    const staleBadge = r.stale ? ' <span class="badge b-other" title="Latest NAV is ' + (r.staleDays || '?') + ' days old — short-period returns suppressed">stale</span>' : '';
    const planBadge = ((r.plan || 'Direct') === 'Regular')
      ? ' <span class="badge b-plan-reg" title="Regular plan — older funds carry full pre-2013 history">REG</span>'
      : ' <span class="badge b-plan-dir" title="Direct plan">DIR</span>';
    tr.innerHTML =
      '<td class="px-2 py-2 text-slate-500 text-[10px]">' + (i + 1) + '</td>' +
      '<td class="px-3 py-2"><div class="text-xs"><span class="font-medium text-slate-800 cursor-pointer hover:text-blue-600 hover:underline" data-detail="' + r.code + '" title="Click for monthly & rolling-return calendars">' + cleanName(r.short).replace(/[<>]/g, '') + '</span>' + planBadge + staleBadge + '</div>' +
        (r.amc ? '<div class="text-[10px] text-slate-500">' + r.amc.replace(/[<>]/g, '') + '</div>' : '') + '</td>' +
      '<td class="px-2 py-2 text-right text-slate-300 italic text-[10px]">—</td>' +
      '<td class="px-2 py-2"><span class="badge ' + badgeClass(r.g) + '" title="' + (r.category || '').replace(/["<>]/g, '') + '">' + r.s + '</span></td>' +
      '<td class="px-2 py-2 text-right text-slate-600">' + r.years.toFixed(1) + '</td>' +
      '<td class="px-2 py-2 text-right border-l border-slate-200">' + fmtRet(r.r1d) + '</td>' +
      '<td class="px-2 py-2 text-right">' + fmtRet(r.r1w) + '</td>' +
      '<td class="px-2 py-2 text-right">' + fmtRet(r.r1m) + '</td>' +
      '<td class="px-2 py-2 text-right">' + fmtRet(r.r3m) + '</td>' +
      '<td class="px-2 py-2 text-right">' + fmtRet(r.r6m) + '</td>' +
      '<td class="px-2 py-2 text-right">' + fmtRet(r.r1y) + '</td>' +
      '<td class="px-2 py-2 text-right border-l border-slate-200">' + fmtRet(r.r3y) + '</td>' +
      '<td class="px-2 py-2 text-right">' + fmtRet(r.r5y) + '</td>' +
      '<td class="px-2 py-2 text-right">' + fmtRet(r.r10y) + '</td>' +
      '<td class="px-2 py-2 text-right border-l border-slate-200 text-sm ' + (cagr >= 0 ? 'pos' : 'neg') + '">' + (cagr >= 0 ? '+' : '') + cagr.toFixed(2) + '</td>' +
      '<td class="px-2 py-2 text-right border-l-2 border-amber-200 bg-amber-50/40">' + fmtRet(r.cust) + '</td>';
    frag.appendChild(tr);
  });
  tbody.appendChild(frag);

  // Stats
  document.getElementById('statShown').textContent = SHOWN.length.toLocaleString() + (SHOWN.length > 1500 ? '  (first 1,500 rendered)' : '');
  const cs = new Set(SHOWN.map(r => r.s));
  document.getElementById('statCats').textContent = cs.size;
  if (SHOWN.length) {
    const avg = SHOWN.reduce((s, r) => s + (r.cagrPct || 0), 0) / SHOWN.length;
    document.getElementById('statCagr').textContent = (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%';
    const top = SHOWN[0];
    const lbl = top.short + '  (' + top.cagrPct.toFixed(1) + '% CAGR)';
    const e = document.getElementById('statBest');
    e.textContent = lbl;
    e.setAttribute('title', lbl);
  } else {
    document.getElementById('statCagr').textContent = '—';
    document.getElementById('statBest').textContent = '—';
  }
  custHint();
}

// A window can be perfectly valid yet blank out every visible row — most often because the From
// date predates 2013 while the plan filter is on Direct (direct plans only exist from Jan 2013),
// or because every fund in the current filter launched later. Say which, instead of a bare "—".
function custHint() {
  const el = document.getElementById('custWarn');
  if (!el) return;
  if (!FROM || !TO || !HIST || SHOWN.some(r => r.cust != null)) { el.textContent = ''; el.classList.add('hidden'); return; }
  const plan = document.getElementById('planFilter').value;
  const anyPlan = ALL.some(r => r.cust != null && (r.plan || 'Direct') !== plan);
  el.textContent = (plan === 'Direct' && anyPlan && FROM < '2013-01-01')
    ? '⚠ No Direct-plan fund existed on ' + FROM + ' — direct plans only start from Jan 2013. Switch Plan to Regular, or pick a later From date.'
    : '⚠ No fund in the current filter has NAV going back to ' + FROM + ' — pick a later From date or widen the filters.';
  el.classList.remove('hidden');
}

// Wire events
document.addEventListener('DOMContentLoaded', () => {
  loadData().then(() => {
    document.getElementById('searchBox').addEventListener('input', render);
    document.getElementById('catFilter').addEventListener('change', render);
    document.getElementById('planFilter').addEventListener('change', render);
    document.getElementById('yrFilter').addEventListener('change', render);

    // Custom date-range window: recompute the per-fund window return, sort by it.
    async function applyDateRange() {
      const f = document.getElementById('fromDate').value, t = document.getElementById('toDate').value;
      if (f && t && !HIST) {
        const info = document.getElementById('rangeInfo'); if (info) info.textContent = 'Loading price history…';
        if (!await ensureHistory()) { if (info) info.textContent = 'Couldn’t load price history. Retry.'; return; }
      }
      recomputeCust();
      if (FROM && TO) SORT = { key: 'cust', dir: -1 };
      else if (SORT.key === 'cust') SORT = { key: 'cagrPct', dir: -1 };
      render();
    }
    document.getElementById('fromDate').addEventListener('change', applyDateRange);
    document.getElementById('toDate').addEventListener('change', applyDateRange);
    document.getElementById('custMode').addEventListener('change', applyDateRange);
    document.getElementById('clearDates').addEventListener('click', () => {
      document.getElementById('fromDate').value = '';
      document.getElementById('toDate').value = '';
      applyDateRange();
    });

    // Fund detail modal — click a fund name to see its monthly/trailing/forward calendars
    document.getElementById('resultsBody').addEventListener('click', e => {
      const t = e.target.closest('[data-detail]');
      if (t) showFundDetail(+t.dataset.detail);
    });
    document.getElementById('detClose').addEventListener('click', closeFundDetail);
    document.getElementById('detWin').addEventListener('change', renderDetail);
    document.getElementById('detailModal').addEventListener('click', closeFundDetail);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeFundDetail(); });

    document.getElementById('resetBtn').addEventListener('click', () => {
      document.getElementById('searchBox').value = '';
      document.getElementById('catFilter').value = 'all';
      document.getElementById('planFilter').value = 'Direct';
      document.getElementById('yrFilter').value = '0';
      document.getElementById('fromDate').value = '';
      document.getElementById('toDate').value = '';
      document.getElementById('custMode').value = 'abs';
      recomputeCust();
      SORT = { key: 'cagrPct', dir: -1 };
      render();
    });
    // Sortable headers
    document.querySelectorAll('th[data-sort]').forEach(th => {
      th.addEventListener('click', () => {
        const k = th.getAttribute('data-sort');
        if (SORT.key === k) SORT.dir = -SORT.dir;
        else { SORT.key = k; SORT.dir = (k === 'name' || k === 's') ? 1 : -1; }
        document.querySelectorAll('.sort-ind').forEach(el => { el.textContent = '↕'; el.className = 'sort-ind text-slate-300'; });
        const ind = th.querySelector('.sort-ind');
        ind.textContent = SORT.dir === -1 ? '▼' : '▲';
        ind.className = 'sort-ind text-blue-600';
        render();
      });
    });
  });
});
</script>
</body>
</html>
"""
HTML = (
    HTML.replace("__B64__", b64).replace("__GEN__", gen).replace("__HIST_LO__", hist_lo).replace("__HIST_HI__", hist_hi)
)
OUT.write_text(HTML, encoding="utf-8")
print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")
