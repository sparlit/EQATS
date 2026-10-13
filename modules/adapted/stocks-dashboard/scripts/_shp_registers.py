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


"""Official registers for Indian institutions (§164s, user 2026-10-04 "use registers for 4"): IRDAI life / general insurers,
PFRDA's NPS Trust, SEBI-registered AIFs named by their registration, RBI-registered NBFCs / scheduled commercial banks. A named
holder matched here is a DOMESTIC institution whatever row the filer put it on (rule 4). Matching is on whole words, so 'LIC'
never matches 'PUBLIC' (THAI UNION ... PUBLIC CO LTD). Built 2026-10-04/05 from the regulators' published lists."""
import difflib
import re

LIFE = [
    (
        "LIFE INSURANCE CORPORATION OF INDIA",
        512,
        "Life Insurance Corporation of India",
        ["LIC OF INDIA", "LICI"],
    ),
    (
        "AXIS MAX LIFE",
        104,
        "Axis Max Life Insurance Ltd (formerly Max Life)",
        ["MAX LIFE", "MAX  LIFE", "MAC LIFE"],
    ),
    (
        "HDFC LIFE",
        101,
        "HDFC Life Insurance Co Ltd (formerly HDFC Standard Life)",
        ["HDFC STANDARD", "HDFC STANDRAD", "HDFCSTANDARD", "HDFC SL "],
    ),
    (
        "ICICI PRUDENTIAL LIFE",
        105,
        "ICICI Prudential Life Insurance Co Ltd",
        [
            "ICICI PRU",
            "ICICI PREDUNTIAL",
            "ICICI PURTENTIAL",
            "ICICI PREDEMTIAL",
            "CICI PRUDENTIAL",
        ],
    ),
    (
        "KOTAK MAHINDRA LIFE",
        107,
        "Kotak Mahindra Life Insurance Co Ltd (formerly Kotak Mahindra Old Mutual)",
        ["KOTAK MAHINDRA OLD MUTUAL", "KOTAK LIFE"],
    ),
    (
        "ADITYA BIRLA SUN LIFE INSURANCE",
        109,
        "Aditya Birla Sun Life Insurance Co Ltd (formerly Birla Sun Life Insurance)",
        ["BIRLA SUN LIFE INSURANCE", "BIRLA SUNLIFE INSURANCE"],
    ),
    (
        "TATA AIA LIFE",
        110,
        "Tata AIA Life Insurance Co Ltd",
        ["TATA AIF LIFE", "TATA LIFE INSURANCE"],
    ),
    ("SBI LIFE", 111, "SBI Life Insurance Co Ltd", []),
    (
        "BAJAJ ALLIANZ LIFE",
        116,
        "Bajaj Life Insurance Ltd (formerly Bajaj Allianz Life)",
        ["BAJAJ ALLIANCE LIFE", "BAJAJ ALIANCE LIFE"],
    ),
    ("PNB METLIFE", 117, "PNB MetLife India Insurance Co Ltd", []),
    (
        "RELIANCE NIPPON LIFE",
        121,
        "IndusInd Nippon Life Insurance Co Ltd (formerly Reliance Nippon / Reliance Life)",
        ["RELIANCE LIFE INSURANCE"],
    ),
    ("AVIVA LIFE", 122, "Aviva Life Insurance Co India Ltd", []),
    ("SHRIRAM LIFE", 128, "Shriram Life Insurance Co Ltd", []),
    ("BHARTI AXA LIFE", 130, "Bharti Life Insurance Co Ltd (formerly Bharti AXA Life)", []),
    (
        "FUTURE GENERALI INDIA LIFE",
        133,
        "Generali Central Life Insurance Co Ltd (formerly Future Generali India Life)",
        [],
    ),
    (
        "IDBI FEDERAL LIFE",
        135,
        "Ageas Federal Life Insurance Co Ltd (formerly IDBI Federal Life)",
        ["AGEAS FEDERAL"],
    ),
    (
        "CANARA HSBC",
        136,
        "Canara HSBC Life Insurance Co Ltd (formerly Canara HSBC Oriental Bank of Commerce Life)",
        [],
    ),
    (
        "PRAMERICA LIFE",
        140,
        "Pramerica Life Insurance Co Ltd (formerly DHFL Pramerica Life)",
        ["DHFL PRAMERICA"],
    ),
    ("STAR UNION DAI", 142, "Star Union Dai-ichi Life Insurance Co Ltd", []),
    ("INDIAFIRST LIFE", 143, "IndiaFirst Life Insurance Co Ltd", []),
    (
        "EDELWEISS TOKIO LIFE",
        147,
        "Edelweiss Life Insurance Co Ltd (formerly Edelweiss Tokio Life)",
        ["EDELWEISS LIFE"],
    ),
]
GEN = [
    ("ICICI LOMBARD", "ICICI Lombard General Insurance Co Ltd"),
    ("BAJAJ ALLIANZ GENERAL", "Bajaj General Insurance Ltd (formerly Bajaj Allianz General)"),
    ("HDFC ERGO", "HDFC ERGO General Insurance Co Ltd"),
    ("IFFCO TOKIO", "IFFCO TOKIO General Insurance Co Ltd"),
    ("NEW INDIA ASSURANCE", "The New India Assurance Co Ltd"),
    ("ORIENTAL INSURANCE", "The Oriental Insurance Co Ltd"),
    ("UNITED INDIA INSURANCE", "United India Insurance Co Ltd"),
    ("NATIONAL INSURANCE", "National Insurance Co Ltd"),
    ("TATA AIG", "Tata AIG General Insurance Co Ltd"),
    ("SBI GENERAL", "SBI General Insurance Co Ltd"),
    ("CHOLAMANDALAM MS", "Cholamandalam MS General Insurance Co Ltd"),
    ("ROYAL SUNDARAM", "Royal Sundaram General Insurance Co Ltd"),
    ("RELIANCE GENERAL", "IndusInd General Insurance Co Ltd (formerly Reliance General)"),
    ("FUTURE GENERALI INDIA INSURANCE", "Generali Central Insurance Co Ltd"),
    ("UNIVERSAL SOMPO", "Universal Sompo General Insurance Co Ltd"),
    ("LIBERTY", "Liberty General Insurance Ltd"),
    ("MAGMA HDI", "Magma General Insurance Ltd"),
    ("AGRICULTURE INSURANCE", "Agriculture Insurance Co of India Ltd"),
    ("ECGC", "ECGC Ltd"),
]
OTHER = [
    (
        "GENERAL INSURANCE CORPORATION",
        "General Insurance Corporation of India (Indian reinsurer, IRDAI-registered)",
    ),
    (
        "NPS TRUST",
        "NPS Trust - National Pension System Trust, set up by PFRDA under the Indian Trusts Act (2008), registered owner of all NPS assets",
    ),
    ("NATIONAL PENSION SYSTEM", "NPS Trust - set up by PFRDA under the Indian Trusts Act (2008)"),
    (
        "EDELWEISS ALTERNATIVE INVESTMENT OPPORTUNITIES",
        "Edelweiss Alternative Investment Opportunities Trust - SEBI Category II AIF, reg. IN/AIF2/17-18/0502",
    ),
    (
        "BAJAJ HOLDINGS",
        "Bajaj Holdings & Investment Ltd - RBI-registered NBFC, CoR N-13.01952 (and the issuer's own 2022-form filing lists it under NBFCs registered with RBI)",
    ),
    ("AXIS BANK", "Axis Bank Ltd - RBI scheduled commercial bank (Indian private sector)"),
    ("INDUSIND BANK", "IndusInd Bank Ltd - RBI scheduled commercial bank (Indian private sector)"),
    ("HDFC BANK", "HDFC Bank Ltd - RBI scheduled commercial bank (Indian private sector)"),
    ("AU SMALL FINANCE BANK", "AU Small Finance Bank Ltd - RBI-licensed small finance bank"),
    (
        "KOTAK MAHINDRA BANK",
        "Kotak Mahindra Bank Ltd - RBI scheduled commercial bank (Indian private sector)",
    ),
    ("STATE BANK OF INDIA", "State Bank of India - RBI scheduled commercial bank (public sector)"),
    ("ICICI BANK", "ICICI Bank Ltd - RBI scheduled commercial bank (Indian private sector)"),
    ("BANK OF BARODA", "Bank of Baroda - RBI scheduled commercial bank (public sector)"),
    (
        "PUNJAB NATIONAL BANK",
        "Punjab National Bank - RBI scheduled commercial bank (public sector)",
    ),
    ("CANARA BANK", "Canara Bank - RBI scheduled commercial bank (public sector)"),
    ("UNION BANK OF INDIA", "Union Bank of India - RBI scheduled commercial bank (public sector)"),
    ("YES BANK", "Yes Bank Ltd - RBI scheduled commercial bank (Indian private sector)"),
    ("IDFC FIRST BANK", "IDFC First Bank Ltd - RBI scheduled commercial bank"),
    ("FEDERAL BANK", "The Federal Bank Ltd - RBI scheduled commercial bank"),
    ("BANDHAN BANK", "Bandhan Bank Ltd - RBI scheduled commercial bank"),
    ("IDBI BANK", "IDBI Bank Ltd - RBI scheduled commercial bank"),
    (
        "THREPSI CARE",
        "Threpsi Care LLP - the issuer's own 2022-form filing places it under Alternative Investment Funds",
    ),
    (
        "ALTERNATE INVESTMENT FUND",
        "row/holder labelled Alternative Investment Fund (SEBI AIF category)",
    ),
]


def norm(s):
    return re.sub(r"\s+", " ", (s or "").upper())


def _has(n, k):
    return re.search(r"(?<![A-Z0-9])" + re.escape(k.strip()) + r"(?![A-Z0-9])", n) is not None


def register(name):
    n = norm(name)
    for key in (
        "NPS TRUST",
        "NATIONAL PENSION SYSTEM",
    ):  # an NPS scheme account names its pension-fund manager (LIC / SBI / UTI ...)
        if _has(n, key):
            return dict(OTHER)[key]
    # bare 'LIC' only as the name's FIRST word, never LIC Housing Finance / LIC Mutual Fund (Indian, but not the insurer) and never
    # a filer's typo for LLC ('Matrix Partners India Investment Holdings, Lic' - TREEHOUSE Dec-2015, found by the FII session)
    if re.match(r"LIC\b", n) and not re.search(r"HOUSING|\bHFL\b|\bMF\b|MUTUAL", n):
        return "IRDAI-registered life insurer no. 512: Life Insurance Corporation of India"
    for key, no, full, alts in LIFE:
        if _has(n, key) or any(_has(n, a) for a in alts):
            return "IRDAI-registered life insurer no. %d: %s" % (no, full)
    for key, full in GEN:
        if _has(n, key) and (key != "LIBERTY" or "INSUR" in n):
            return f"IRDAI-registered general insurer: {full}"
    for key, full in OTHER:
        if _has(n, key):
            return full
    if re.search(r"LIFE INSUR|INSURANCE CO", n):
        best = max(
            ((difflib.SequenceMatcher(None, n, k).ratio(), no, full) for k, no, full, _ in LIFE),
            default=None,
        )
        if best and best[0] > 0.6:
            return "IRDAI-registered life insurer no. %d: %s (name as misspelt in the filing)" % (
                best[1],
                best[2],
            )
    return None
