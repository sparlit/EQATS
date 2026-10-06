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


# -*- coding: utf-8 -*-
"""Nifty SME Emerge — NSE Indices press releases → dated index changes  (runbook §208).

NSE Indices announces EVERY change to Nifty SME Emerge in a press release (Press_Release/ind_prsDDMMYYYY[_n].pdf):
  - the quarterly reviews, inside the big "Replacements in indices" release ("4) Nifty SME Emerge",
    "a) Nifty SME Emerge", "y) NIFTY SME EMERGE" …), effective the working day after the last Thursday of
    Mar / Jun / Sep / Dec (methodology);
  - one-off exclusions on a migration to the main board, suspension, Z category ("Exclusion from Nifty SME Emerge
    index", "Replacement in NIFTY SME EMERGE Index" — a whole release about the index);
  - revocations ("revoke its earlier decision of inclusion of X (SYM) in NIFTY SME EMERGE index effective D") and
    re-dated exclusions — read as text, never inferred.

parse_text(text) -> {"eff": ISO|None, "ex": [[SYM, name]…], "inc": [[SYM, name]…], "revoke": [[SYM, ISO]…],
                     "gaps": [...], "sme": bool}
  `eff` = the first "effective (from) <Month D, YYYY>" inside the Nifty SME Emerge section, else the release's own
  (a big release carries one date per section; the SME section's own wins), else the first date after it.
  A table row is "<n> <Company name> <SYMBOL>"; numbering that is not 1..n is reported in `gaps` (a row the text
  layer split) so the caller can refuse it.
"""
import datetime
import re

MON = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}
DRE = re.compile(r"effective\s+(?:from\s+|of\s+)?([A-Z][a-z]+)\s+(\d{1,2})\s*,?\s*(\d{4})", re.I)
ROW = re.compile(r"^\s*(\d{1,3})\s+(.+?)\s+([A-Z][A-Z0-9&\-]{1,19})\s*$")
HEAD = re.compile(r"^\s*(\d{1,2}\)|[A-Za-z]{1,3}\)|[A-H]\.)\s+\S")
SME = re.compile(r"SME\s*EMERGE", re.I)
REVOKE = re.compile(
    r"revoke\s*its\s*earlier\s*decision\s*of\s*inclusion\s*of\s*(.{0,160}?)\s*in\s*NIFTY\s*SME\s*EMERGE"
    r"\s*index\s*effective\s*([A-Z][a-z]+)\s+(\d{1,2})\s*,\s*(\d{4})",
    re.I,
)
NOT_SYM = {"IMSC", "NSE", "IISL", "SME", "ETL", "MWL"}


def _d(m):
    return datetime.date(int(m[2]), MON[m[0].lower()], int(m[1])).isoformat()


def _norm(t):
    return re.sub(r"SME\s*\n\s*EMERGE", "SME EMERGE", t, flags=re.I)


def _section(L):
    s = next((i for i, l in enumerate(L) if HEAD.match(l) and SME.search(l)), None)
    if s is None:
        return None, None
    e = len(L)
    for j in range(s + 1, len(L)):
        l = L[j]
        if (
            (HEAD.match(l) and not re.match(r"^\s*\d{1,3}\s", l))
            or re.match(r"\s*(About N|For detailed criteria)", l)
            or re.match(r"\s*No changes? (is|are) being made (in|to) (?!the index)", l, re.I)
        ):
            e = j
            break
    return s, e


def parse_text(text):
    t = _norm(text)
    L = t.split("\n")
    head = " ".join(L[:12])
    s, e = _section(L)
    if s is None:
        if SME.search(head):
            s = 0
        else:  # no heading names the index: the paragraph that does opens the section (ind_prs30092020)
            s = next((i for i, l in enumerate(L) if SME.search(l)), None)
            if s is None:
                return {"sme": False}
        e = next(
            (
                j
                for j in range(s + 1, len(L))
                if re.match(r"\s*About N", L[j])
                or (HEAD.match(L[j]) and not re.match(r"^\s*\d{1,3}\s", L[j]))
            ),
            len(L),
        )
    mode, ex, inc, nums = None, [], [], {"ex": [], "inc": []}
    for l in L[s:e]:
        r = ROW.match(l)
        if r and mode and not re.match(r"\s*\d+\s+Company", l):
            (ex if mode == "ex" else inc).append([r.group(3), r.group(2).strip()])
            nums[mode].append(int(r.group(1)))
            continue
        a, b = re.search(r"exclu", l, re.I), re.search(r"inclu", l, re.I)
        if a and not b:
            mode = "ex"
        elif b and not a:
            mode = "inc"
    body, pre, post = "\n".join(L[s:e]), "\n".join(L[:s]), "\n".join(L[e:])
    own = [_d(x) for x in DRE.findall(body)]
    if own:
        eff = own[0]
    else:
        before = [_d(x) for x in DRE.findall(pre)]
        after = [_d(x) for x in DRE.findall(post)]
        eff = before[-1] if before else (after[0] if after else None)
    flat = " ".join(t.split())
    rev = []
    for m in REVOKE.finditer(flat):
        syms = re.findall(r"\(([A-Z][A-Z0-9&\-]+)\)", m.group(1)) or [
            x
            for x in re.findall(r"\(([A-Z][A-Z0-9&\-]+)\)", flat[max(0, m.start() - 700) : m.end()])
            if x not in NOT_SYM
        ]
        if syms:
            rev.append([syms[0], _d(m.groups()[1:])])
    gaps = [k for k, v in nums.items() if v and v != list(range(1, len(v) + 1))]
    return {"sme": True, "eff": eff, "ex": ex, "inc": inc, "revoke": rev, "gaps": gaps}
