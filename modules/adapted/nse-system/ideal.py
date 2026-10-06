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


"""Ideal value bands ("actual vs ideal") for every number the portal shows.

WHY
A number alone is meaningless to someone who is not a finance person. "ROCE 8.1"
says nothing; "ROCE 8.1% - below the 15% we look for" says everything.

WHERE THE BANDS COME FROM (this matters - they are not invented)
1. This system's own rules, which are the authority here:
     strategy_config.SCREENER / SETUP, scoring.py's gate thresholds,
     fund_veto.py's disqualification levels.
2. The traders library: thresholds actually written into the 14 book methods
   (e.g. O'Shaughnessy's value screens, Lowe's and Parikh's 9 deterioration
   tests in EXIT_LOGIC.md).
3. Long-standing convention in Indian equity analysis, used only where (1) and
   (2) are silent - and labelled as convention so it is never confused with a
   tested system rule.

Every band carries a `source` so the owner can see WHY a number is "good".
`direction` says whether higher or lower is better, because for debt or P/E
lower is better and a naive "bigger = greener" would mislead.

USAGE
    from ideal import assess
    assess("roce", 8.1)
    # -> {"key","label","actual","ideal_text","verdict","pct","source","hint"}

`verdict` is one of: good / ok / poor / unknown / high / low.
"""

# kind: "higher" better | "lower" better | "band" ideal inside a range
BANDS = {
    # ---------------------------------------------------------- profitability
    "roce": {
        "label": "Return on capital",
        "unit": "%",
        "kind": "higher",
        "good": 15.0,
        "ok": 10.0,
        "ideal_text": "15% or more",
        "source": "system rule (top band in scoring.py) and Lowe/Parikh exit tests",
        "hint": "How much profit the company squeezes out of every ₹100 it "
        "invests in the business. Higher means a better business.",
    },
    "roe": {
        "label": "Return on shareholder money",
        "unit": "%",
        "kind": "higher",
        "good": 15.0,
        "ok": 12.0,
        "ideal_text": "15% or more",
        "source": "trader thresholds (quantitative_value, Lowe) and convention",
        "hint": "Profit earned on the owners' money. Like interest on your own "
        "deposit, but for a whole company.",
    },
    "operating_margin": {
        "label": "Profit kept from each sale",
        "unit": "%",
        "kind": "higher",
        "good": 15.0,
        "ok": 8.0,
        "ideal_text": "15% or more",
        "source": "system rule (rule_engine seed: operating margin >= 8)",
        "hint": "Of every ₹100 of sales, how much is left after running the business.",
    },
    "net_profit_margin": {
        "label": "Profit left at the end",
        "unit": "%",
        "kind": "higher",
        "good": 10.0,
        "ok": 5.0,
        "ideal_text": "10% or more",
        "source": "convention",
        "hint": "What finally remains after every cost, interest and tax.",
    },
    # ------------------------------------------------------------ safety
    "debt_to_equity": {
        "label": "Borrowing vs own money",
        "unit": "x",
        "kind": "lower",
        "good": 0.5,
        "ok": 1.0,
        "ideal_text": "below 0.5x (blocked above 3x)",
        "source": "system rules - scoring gate at 1.5x, hard block above 3x (fund_veto)",
        "hint": "For every ₹1 the owners put in, how much is borrowed. High "
        "borrowing magnifies both gains and disasters.",
    },
    "interest_coverage": {
        "label": "Cushion for interest bills",
        "unit": "x",
        "kind": "higher",
        "good": 3.0,
        "ok": 1.5,
        "ideal_text": "3x or more",
        "source": "convention",
        "hint": "How many times over the company could pay its interest bill "
        "from profits. Below 1 means it cannot.",
    },
    "cfo_positive": {
        "label": "Cash actually coming in",
        "unit": "",
        "kind": "bool_good_true",
        "ideal_text": "yes - cash coming in",
        "source": "system rule (scoring gate and the Lowe/Parikh exit tests)",
        "hint": "A company can report profit yet still bleed cash. This asks "
        "whether real cash arrived.",
    },
    # ------------------------------------------------------------ valuation
    "pe": {
        "label": "Price vs yearly profit",
        "unit": "x",
        "kind": "lower",
        "good": 15.0,
        "ok": 25.0,
        "ideal_text": "under 15x, ideally near or below its industry's average",
        "source": "trader screens (O'Shaughnessy low-PE) and convention",
        "hint": "How many years of current profit you are paying for the whole "
        "company. Lower is cheaper, but a very low number can mean the "
        "market expects trouble.",
    },
    "pb": {
        "label": "Price vs book value",
        "unit": "x",
        "kind": "lower",
        "good": 1.5,
        "ok": 3.0,
        "ideal_text": "under 1.5x",
        "source": "trader screens (Graham deep-value, quantitative_value)",
        "hint": "Compared with the company's net assets on paper. Below 1 means "
        "you pay less than the assets are worth.",
    },
    "dividend_yield": {
        "label": "Yearly cash paid to owners",
        "unit": "%",
        "kind": "higher",
        "good": 3.0,
        "ok": 1.0,
        "ideal_text": "3% or more",
        "source": "trader screens (O'Shaughnessy high-dividend) and convention",
        "hint": "Like rent from a property - cash in hand each year, before any price change.",
    },
    "peg": {
        "label": "Price paid for growth",
        "unit": "x",
        "kind": "lower",
        "good": 1.0,
        "ok": 2.0,
        "ideal_text": "under 1.0x - growth costs less than it is worth",
        "source": "system rule (positional_scanner value bands)",
        "hint": "Price-to-profit divided by the growth rate. Near or below 1 is "
        "considered reasonable.",
    },
    # ------------------------------------------------------------ growth
    "sales_growth_3y": {
        "label": "Sales growth, 3 years",
        "unit": "%",
        "kind": "higher",
        "good": 15.0,
        "ok": 10.0,
        "ideal_text": "15% or more a year",
        "source": "trader thresholds (Lowe and Parikh deterioration tests use 10%) and convention",
        "hint": "Is the business getting bigger, and how fast.",
    },
    "profit_growth_3y": {
        "label": "Profit growth, 3 years",
        "unit": "%",
        "kind": "higher",
        "good": 15.0,
        "ok": 10.0,
        "ideal_text": "15% or more a year",
        "source": "trader thresholds (Lowe and Parikh deterioration tests use 10%) and convention",
        "hint": "Are profits growing, ideally at least as fast as sales.",
    },
    # ------------------------------------------------------------ ownership
    "promoter_holding": {
        "label": "How much owners keep",
        "unit": "%",
        "kind": "higher",
        "good": 50.0,
        "ok": 25.0,
        "ideal_text": "50% or more (blocked below 20%)",
        "source": "system rules - Lowe/Parikh test at 50%, hard block below 20% (fund_veto)",
        "hint": "Founders holding a large stake usually care more about the "
        "company's long-term health.",
    },
    "pledge_pct": {
        "label": "Owner shares pledged as collateral",
        "unit": "%",
        "kind": "lower",
        "good": 5.0,
        "ok": 20.0,
        "ideal_text": "under 5% (warning above 20%)",
        "source": "system rule (scoring gate at 5, Lowe/Parikh test at 20)",
        "hint": "Shares used as loan security. A lot of pledging is a warning sign.",
    },
    "fii_holding": {
        "label": "Held by foreign institutions",
        "unit": "%",
        "kind": "higher",
        "good": 10.0,
        "ok": 3.0,
        "ideal_text": "10% or more",
        "source": "convention",
        "hint": "Professional overseas funds see something worth owning.",
    },
    # ------------------------------------------------------------ risk / plan
    "risk_pct": {
        "label": "How much you risk",
        "unit": "%",
        "kind": "lower",
        "good": 3.0,
        "ok": 5.0,
        "ideal_text": "3% or less; the system skips anything above 5%",
        "source": "system rule (SETUP.MAX_STOP_PCT = 5%)",
        "hint": "The gap between where you buy and where you admit you were wrong.",
    },
    "shape_score": {
        "label": "How tidy the pause is",
        "unit": "/100",
        "kind": "higher",
        "good": 60.0,
        "ok": 40.0,
        "ideal_text": "60 or more",
        "source": "system rule (trader_league confidence bands: 60 high, 40 medium)",
        "hint": "A calm, even pause is more likely to continue than a jagged one.",
    },
    "p_win": {
        "label": "Chance of a good move",
        "unit": "%",
        "kind": "higher",
        "good": 60.0,
        "ok": 50.0,
        "ideal_text": "well above 50% is the model's real interest",
        "source": "system model output; the owner's own record shows scores near "
        "50% are close to a coin flip",
        "hint": "The model's estimate, not a promise. The system's measured "
        "win rate has been far lower than the model implies.",
    },
    # ------------------------------------------------------------ market
    "breadth_above50": {
        "label": "Shares taking part in the rise",
        "unit": "",
        "kind": "higher",
        "good": 0.6,
        "ok": 0.5,
        "ideal_text": "above 0.50 - more than half",
        "source": "system rule (breadth gate: above50 >= 0.50 and advancers >= decliners)",
        "hint": "A rise carried by most shares is healthier than one carried by a few.",
    },
    "delivery": {
        "label": "Shares actually held overnight",
        "unit": "",
        "kind": "higher",
        "good": 0.7,
        "ok": 0.5,
        "ideal_text": "maps 30% delivery to 0.0 and 80% to 1.0",
        "source": "system rule (top_picks delivery conviction curve)",
        "hint": "High delivery means buyers kept the shares instead of flipping them.",
    },
}

# Friendly groupings so a UI can present these as sections.
GROUPS = [
    ("Business quality", ["roce", "roe", "operating_margin", "net_profit_margin"]),
    ("Safety", ["debt_to_equity", "interest_coverage", "cfo_positive"]),
    ("Price you pay", ["pe", "pb", "peg", "dividend_yield"]),
    ("Growth", ["sales_growth_3y", "profit_growth_3y"]),
    ("Who owns it", ["promoter_holding", "pledge_pct", "fii_holding"]),
    (
        "Your plan and the market",
        ["risk_pct", "shape_score", "p_win", "breadth_above50", "delivery"],
    ),
]


def _fmt(value, unit):
    if value is None:
        return "no data"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(num - round(num)) < 1e-9:
        shown = f"{int(round(num))}"
    else:
        shown = f"{num:.2f}".rstrip("0").rstrip(".")
    return f"{shown}{unit}" if unit else shown


def assess(key, actual):
    """Compare one value with its ideal band.

    Returns None when the key is unknown, so callers can render nothing rather
    than guess. Never raises on bad input - a missing value becomes 'no data'.
    """
    band = BANDS.get(key)
    if band is None:
        return None

    unit = band.get("unit", "")
    out = {
        "key": key,
        "label": band["label"],
        "unit": unit,
        "ideal_text": band["ideal_text"],
        "source": band["source"],
        "hint": band["hint"],
        "direction": band["kind"],
        "actual": actual,
        "actual_text": _fmt(actual, unit),
        "ideal_display": _fmt(band.get("good"), unit) if band.get("good") is not None else None,
        "ok_display": _fmt(band.get("ok"), unit) if band.get("ok") is not None else None,
        "verdict": "unknown",
        "message": "No value stored for this measure yet.",
    }

    if actual is None:
        return out

    kind = band["kind"]

    if kind == "bool_good_true":
        truthy = actual in (True, 1, "1", "yes", "true", "True")
        out["verdict"] = "good" if truthy else "poor"
        out["message"] = (
            "Cash is coming in."
            if truthy
            else "Profit is reported but no cash arrived - a warning."
        )
        return out

    try:
        value = float(actual)
    except (TypeError, ValueError):
        return out

    good = band.get("good")
    ok = band.get("ok")

    if kind == "higher":
        if good is not None and value >= good:
            out["verdict"], out["message"] = "good", f"Meets the {band['ideal_text']} target."
        elif ok is not None and value >= ok:
            out["verdict"], out["message"] = (
                "ok",
                f"Acceptable, but below the {band['ideal_text']} we look for.",
            )
        else:
            out["verdict"], out["message"] = "poor", f"Below the {band['ideal_text']} we look for."
    elif kind == "lower":
        if good is not None and value <= good:
            out["verdict"], out["message"] = "good", f"Meets the {band['ideal_text']} target."
        elif ok is not None and value <= ok:
            out["verdict"], out["message"] = (
                "ok",
                f"Acceptable, but above the {band['ideal_text']} we look for.",
            )
        else:
            out["verdict"], out["message"] = (
                "poor",
                f"Worse than the {band['ideal_text']} we look for.",
            )
    else:  # band
        low, high = band.get("low"), band.get("high")
        if low is not None and high is not None and low <= value <= high:
            out["verdict"], out["message"] = (
                "good",
                f"Inside the ideal range ({band['ideal_text']}).",
            )
        else:
            out["verdict"], out["message"] = (
                "ok",
                f"Outside the ideal range ({band['ideal_text']}).",
            )

    # Distance from the ideal boundary, as a simple percentage, for a bar width.
    ref = good if good is not None else ok
    if ref not in (None, 0):
        try:
            out["pct_to_ideal"] = (
                round(min(100.0, max(0.0, (value / float(ref)) * 100.0)), 1)
                if kind == "higher"
                else round(min(100.0, max(0.0, (float(ref) / value) * 100.0)), 1)
                if value
                else 100.0
            )
        except ZeroDivisionError:
            out["pct_to_ideal"] = 0.0
    return out


def assess_many(pairs):
    """pairs: iterable of (key, value). Returns only the known ones."""
    out = []
    for key, value in pairs:
        item = assess(key, value)
        if item is not None:
            out.append(item)
    return out


def catalog():
    """All bands, including the numbers the UI needs to judge a value.

    `good`/`ok` are the band boundaries and `direction` says whether higher or
    lower is better, which is what lets the UI colour a value correctly (for
    debt or P/E, lower is better).
    """
    fields = ("label", "unit", "kind", "good", "ok", "ideal_text", "source", "hint")
    return [{"key": k, **{f: v.get(f) for f in fields}} for k, v in sorted(BANDS.items())]
