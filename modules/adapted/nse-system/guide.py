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


def f2(v):
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except Exception:
        return None


FAM_KEYS = {
    "financial": ["BANK", "FINANC", "NBFC"],
    "capital": [
        "INFRA",
        "ENERGY",
        "POWER",
        "UTILITY",
        "TELECOM",
        "METAL",
        "MINING",
        "OIL",
        "CONSTR",
        "REALTY",
        "SHIP",
        "RAIL",
        "AUTO",
    ],
    "quality": ["IT", "SOFTWARE", "TECH", "PHARMA", "HEALTH", "FMCG", "CONSUMER", "MEDIA"],
}


def family(sector):
    s = (sector or "").upper()
    for fam, keys in FAM_KEYS.items():
        for k in keys:
            if k in s:
                return fam
    return "default"


MEANING = {
    "pe": "price you pay per ₹1 of profit",
    "roe": "profit per ₹100 of shareholder money",
    "roce": "profit per ₹100 of total capital (THE quality number)",
    "debt_to_equity": "borrowed money vs own money",
    "profit_growth_3y": "yearly profit compounding over 3 years",
    "sales_growth_3y": "yearly revenue compounding over 3 years",
    "pledge_pct": "promoter shares mortgaged (danger signal)",
    "promoter_holding": "owner's skin in the game",
}


def fund_rows(m, sector, sector_median_pe):
    fam = family(sector)
    rows = []
    pe = f2(m.get("pe"))
    if sector_median_pe:
        ideal = f"below sector median {round(sector_median_pe, 2)}"
        ok = None if pe is None else pe <= sector_median_pe
    else:
        ideal = "vs sector (see Daily Scan)"
        ok = None
    rows.append(("PE — " + MEANING["pe"], pe, ideal, ok))

    roe = f2(m.get("roe"))
    roe_ideal = {"financial": 12, "capital": 12, "quality": 18, "default": 15}[fam]
    rows.append(("ROE — " + MEANING["roe"], roe, f"≥ {roe_ideal}%", None if roe is None else roe >= roe_ideal))

    roce = f2(m.get("roce"))
    roce_ideal = {"financial": 10, "capital": 12, "quality": 25, "default": 15}[fam]
    rows.append(("ROCE — " + MEANING["roce"], roce, f"≥ {roce_ideal}%", None if roce is None else roce >= roce_ideal))

    de = f2(m.get("debt_to_equity"))
    de_ideal = {"financial": None, "capital": 2.0, "quality": 0.5, "default": 1.5}[fam]
    if de_ideal is None:
        rows.append(("Debt/Equity — " + MEANING["debt_to_equity"], de, "not applicable for financials", None))
    else:
        rows.append(
            ("Debt/Equity — " + MEANING["debt_to_equity"], de, f"≤ {de_ideal}", None if de is None else de <= de_ideal)
        )

    pg = f2(m.get("profit_growth_3y"))
    rows.append(("Profit growth 3Y — " + MEANING["profit_growth_3y"], pg, "≥ 15%", None if pg is None else pg >= 15))

    sg = f2(m.get("sales_growth_3y"))
    rows.append(("Sales growth 3Y — " + MEANING["sales_growth_3y"], sg, "≥ 10%", None if sg is None else sg >= 10))

    pl = f2(m.get("pledge_pct"))
    rows.append(("Pledge — " + MEANING["pledge_pct"], pl, "≤ 5 (best is 0)", None if pl is None else pl <= 5))

    ph = f2(m.get("promoter_holding"))
    rows.append(("Promoter holding — " + MEANING["promoter_holding"], ph, "≥ 25%", None if ph is None else ph >= 25))
    return rows
