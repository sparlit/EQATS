# -*- coding: utf-8 -*-
"""Generate a Workflow JS script for one CHUNK of agent-bins (historical fundamentals backfill).
Usage: python -X utf8 _wf_gen.py <chunk_start_bin> <chunk_end_bin_exclusive> > _wf_run.js
Each agent gets a hardcoded symbol list + the full recovery playbook; returns anchor-verified cells.
"""
import json, sys
bins=json.load(open("_wf_bins.json"))
a=int(sys.argv[1]); b=int(sys.argv[2]); chunk=bins[a:b]

PROMPT_TMPL = r'''You recover MISSING historical quarterly NET-PROFIT cells for specific NSE companies, to complete docs/sf_fundamentals.json.

TWO RULES, BOTH NON-NEGOTIABLE:
1. NEVER fabricate: only return a value you ANCHOR-VERIFIED (a source's comparative column EQUALS a stored quarter, OR a 9M/H1/FY reconciliation ties, OR PBT-tax=PAT on the page, OR two INDEPENDENT sources agree to the paisa). Never guess/interpolate/annual-÷4.
2. NEVER skip lazily: the number almost ALWAYS EXISTS somewhere. A SKIP is a LAST RESORT only after you have ACTUALLY OPENED AND READ every source in the SOURCES list below and shown the quarter is in none of them. "Not in the NSE filing" is NOT a reason to skip — it means go to the next source. Do NOT write a skip reason that names a source you did not actually fetch. Most past skips were WRONG because the agent stopped at NSE; e.g. GOCOLORS/LATENTVIEW were "unrecoverable" until someone opened the RHP. Assume the data is gettable and prove otherwise by exhaustion.

ALL commands run from: C:/Users/dhruv/stocks-dashboard/scripts  (cd there first, every Bash call). You may use curl_cffi (impersonate='chrome', headers={'Accept-Encoding':'identity'}) to fetch ANY url, fitz to render PDF pages, and WebSearch/WebFetch to FIND documents.

SOURCES (exhaust ALL before any skip — a pre-listing quarter lives in at least one):
  S1 NSE filings (fetch_nse.py) — post-listing quarterlies + their year-ago/preceding comparative columns.
  S2 BSE filings — BSE hosts results NSE may lack; fetch by scrip via bseindia.com /corporates (announcements/financial-results). Old (~2019-20) results are .zip (use fetch_nse_zip.py-style) or scanned PDFs (render+vision).
  S3 RHP — the FINAL prospectus (NOT just DRHP). web-search "<company> RHP prospectus pdf"; TRY https://d2un9pqbzgw43g.cloudfront.net/main/IPO_RHP_<NAME>.pdf and BSE /corporates/download and SEBI. Restated P&L OFTEN has a "three months ended June 30, 20XX" Q1 stub (+prior-yr) AND the MD&A "Restated (Loss)/Profit after Tax" text states each interim period's PAT in words. This single doc usually yields Jun (direct) + Sep (via 9M-Q1-Q3) + sometimes H1/9M figures.
  S4 DRHP — earlier prospectus; sometimes has different interim stubs than the RHP.
  S5 Company INVESTOR-RELATIONS site — annual reports (5-yr highlights), and especially QUARTERLY INVESTOR PRESENTATIONS / earnings decks which often print the prior-year quarter for YoY. web-search "<company> investor presentation Q_ FY__".
  S6 AGGREGATORS as a LEAD then CONFIRM: screener.in/company/<SYM>/ , trendlyne.com, moneycontrol.com show historical quarterly P&L (they ingest RHP-restated quarters for recent IPOs). Use these to SEE the value, then CONFIRM it against a primary source (S1-S5) OR require a second aggregator to agree to the paisa before accepting. Do NOT accept a lone aggregator number unconfirmed.
  S7 9M/H1/FY RECONSTRUCTION: if you have any 3 of {Q1,Q2,Q3,Q4} and the FY (or any 9M/H1 sub-total) from ANY source, the 4th = subtraction — that is a VALID anchored recovery, not a guess.

YOUR ASSIGNED SYMBOLS: __SYMS__

STEP 1 - Load your gaps + the known series (for anchoring):
  python -X utf8 -c "import json;g=json.load(open('_wf_gaps.json'));[print(s,json.dumps(g[s])) for s in __SYMS_PY__]"
Each company: gaps=[{qe,miss:[bases]}] (what to fill) and series={qe:[std,con]} (already-known values to anchor against). qe is an int like 20210630.

STEP 2 - For each gap cell pick the recovery path:

  (A) CON gap, company had NO subsidiary that period (no-sub identity - FAST, recovers whole runs):
    Companies often began consolidating only on a specific date. Fetch the FIRST consolidated filing (or a recent one) and read the note, e.g. "first consolidated financial results", "no subsidiary/associate/JV", "Company has no subsidiary". If the company had no subsidiary in the gap quarter then consolidated == standalone (SEBI LODR Reg 33 identity): set con = the SERIES std for that quarter (it must already be known).
    PROOF REQUIRED: cite the filing note AND confirm the identity holds where BOTH appear in series (con==std in the overlap quarters). Then extend con=std to the null con quarters that pre-date the first subsidiary.

  (B) Genuine read (std gaps; or con where a subsidiary existed):
    Fetch:  echo '[["SYM",QE],["SYM",QE2]]' > _wf_f_TAG.json   (TAG = your agent id, unique)
            python -X utf8 fetch_nse.py _wf_f_TAG.json 2>&1
    PDFs -> _vpdf/SYM_QE_nse.pdf. Locate the P&L page:
            python -X utf8 _wf_dump.py _vpdf/SYM_QE_nse.pdf std   (or con)
    Text-extract rows (if the PDF has a text layer):
            python -X utf8 _wf_rows.py _vpdf/SYM_QE_nse.pdf PAGE
    If SCANNED (no/garbled text) render + crop + VISION-read:
            python -X utf8 _wf_render.py _vpdf/SYM_QE_nse.pdf PAGE _wf_TAG.png
            python -X utf8 _wf_crop.py _vpdf/SYM_QE_nse.pdf PAGE _wf_TAG.png 0.30 0.65
    then Read the PNG.
    VALUE = "Profit for the period/year" or "Net profit after tax" (NOT total comprehensive income, NOT profit BEFORE tax, NOT a segment line, NOT "profit carried to balance sheet"). For consolidated with minority: use owner/parent-attributable ("attributable to owners of the company"). UNIT: Rupees in Lakh -> /100; Million -> /10; Crore -> as-is. Output crore, 2 decimals.

  (C) INSURER (only if your list has one of LICI/HDFCLIFE/ICICIPRULI/GICRE/NIACL/SBILIFE/ICICIGI/STARHEALTH/GODIGIT/NIVABUPA/MFSL):
    FIRST read scripts/INSURER_EXTRACTION_PLAYBOOK.md and follow it exactly (Shareholders' P&L "Profit after tax"; owner-attributable when minority/associate exists; magnitude ranges; verify vs the year-ago column). Insurer XBRL is unreadable - you MUST read the PDF.

  (D) PRE-LISTING quarter (the company IPO'd AFTER this quarter; you are filling quarters BEFORE its series start, back toward 2020):
    The value appears as a COMPARATIVE column in the EARLIEST post-listing filings, OR as a quarterly STUB in the IPO prospectus.
    - Fetch the FIRST 1-2 post-listing quarterly filings AND the (target qe + 1yr) filing: the +1yr filing's YEAR-AGO column = your
      target quarter; the next filing's PRECEDING-QUARTER column = the quarter just before; for a MARCH target the following-JUNE
      filing's preceding-quarter column = that March.
    - CRITICAL — FETCH THE ACTUAL RHP (final prospectus), NOT just the DRHP. Many RHPs carry a "three months ended June 30, 20XX"
      Q1 STUB (with its prior-year comparative) in the Restated P&L AND/OR the MD&A "Restated (Loss)/Profit after Tax" narrative —
      this gives a pre-listing JUNE quarter DIRECTLY (GOCOLORS & LATENTVIEW were recovered this way AFTER their DRHP looked
      annual-only). Get the RHP: web-search "<company> RHP prospectus pdf"; TRY the banker host
      https://d2un9pqbzgw43g.cloudfront.net/main/IPO_RHP_<NAME>.pdf (NAME e.g. GOFASHION, LATENT, SAPPHIRE) and BSE /corporates/download.
      curl_cffi download, render the P&L/MD&A page with fitz, vision-read it. Then derive the SEP quarter via 9M − Q1(jun) − Q3.
    - ANCHOR (mandatory): the filing/stub's CURRENT or later-year column must EXACTLY equal a stored quarter (fixes scale+basis+column
      mapping); THEN read the target column on the SAME P&L line (owners vs total — match whatever the anchor matched).
      UNIT: Rupees in Lakh /100; Million /10; Crore as-is.
    - Also use H1=Q1+Q2 / 9M=Q1+Q2+Q3 / FY=sum reconciliation against stored quarters.
    - SKIP only AFTER opening the RHP and confirming it has NO quarterly stub, with reason
      "pre-IPO: DRHP+RHP annual-only / no quarterly stub (RHP checked)".

STEP 3 - ANCHOR-VERIFY every value before returning. At least ONE of:
   - the filing's own year-ago / prior-quarter comparative column EQUALS our series value (exact match), OR
   - 9M = Q1+Q2+Q3, or FY = Q1+Q2+Q3+Q4 reconciliation ties, OR
   - Profit-before-tax - tax = profit-after-tax on the page.
   Record the ANNOUNCE DATE (broadcast / board-meeting date shown on the filing or its NSE listing) as int YYYYMMDD when visible; else null.

NSE rate-limits ~8 fetches/session: if fetch_nse.py prints MISS/403, sleep 40s and retry once; batch fetches into one targets file. Use a UNIQUE TAG (your agent label) for all temp files so you do not collide with other agents.

Return ONLY anchor-verified results. Everything you could not verify goes in skipped with a concrete reason. Your final message MUST be the StructuredOutput tool call - no prose.'''

def mk(symlist):
    syms_disp = ", ".join(symlist)
    syms_py = "[" + ",".join("'%s'"%s for s in symlist) + "]"
    p = PROMPT_TMPL.replace("__SYMS__", syms_disp).replace("__SYMS_PY__", syms_py)
    return p

agents_js=[]
for i,binsyms in enumerate(chunk):
    label = "+".join(binsyms)[:40]
    prompt = mk(binsyms)
    agents_js.append("  ()=>agent(%s,{label:%s,phase:'Backfill',schema:SCH}),"%(json.dumps(prompt),json.dumps(label)))

JS = '''export const meta = {
  name: 'hist-fund-backfill-c%d',
  description: 'Historical quarterly net-profit backfill (2020-2026), chunk bins %d-%d',
  phases: [{ title: 'Backfill', detail: '%d agents, anchor-verified filing reads' }],
}
const SCH = {
  type:'object',
  properties:{
    results:{type:'array',items:{type:'object',properties:{
      sym:{type:'string'}, qe:{type:'integer'}, basis:{type:'string',enum:['con','std']},
      value_cr:{type:'number'}, announce_date:{type:['integer','null']},
      anchor:{type:'string'}, confidence:{type:'string',enum:['high','medium']}
    }, required:['sym','qe','basis','value_cr','anchor','confidence']}},
    skipped:{type:'array',items:{type:'object',properties:{
      sym:{type:'string'}, qe:{type:'integer'}, basis:{type:'string'}, reason:{type:'string'}
    }, required:['sym','qe','basis','reason']}}
  },
  required:['results','skipped']
}
phase('Backfill')
const tasks = [
%s
]
const out = await parallel(tasks)
return out.filter(Boolean)
''' % (a, a, b, len(chunk), "\n".join(agents_js))

sys.stdout.write(JS)
