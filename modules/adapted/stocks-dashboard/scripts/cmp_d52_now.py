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
"""Reconcile Trendlyne live screener (dist-from-52w-high<=10, Nifty500) vs OUR 2026-06-12 list.
TL gives company names; map to NSE symbols via bin meta names + manual aliases."""
import gzip
import json
import re

D = json.loads(gzip.decompress(open("docs/sf_stock_data.bin", "rb").read()))
META = D["meta"]
data = D["data"]
mine = json.load(open("scripts/_mine_d52.json"))
OUR = {x[0] for x in mine[max(mine)]}  # 2026-06-12, 123 syms

# Trendlyne live list (d52, name) in displayed order
TL = [
    (9.98, "ICICI Prudential Asset"),
    (9.88, "Exide Industries"),
    (9.88, "Alkem Laboratories"),
    (9.86, "Aditya Infotech"),
    (9.84, "CCL Products"),
    (9.73, "NMDC"),
    (9.73, "LG Electronics"),
    (9.68, "Lenskart Solutions"),
    (9.55, "Allied Blenders"),
    (9.44, "Can Fin Homes"),
    (9.32, "ZF Commercial"),
    (9.07, "Shriram Finance"),
    (9.05, "ACME Solar Holdings"),
    (9.02, "HFCL"),
    (8.99, "Vijaya Diagnostic Centre"),
    (8.96, "Star Health"),
    (8.92, "Engineers India"),
    (8.9, "Lupin"),
    (8.83, "Niva Bupa Health Insurance"),
    (8.82, "Travel Food Services"),
    (8.76, "Eicher Motors"),
    (8.73, "Sammaan Capital"),
    (8.63, "HDFC AMC"),
    (8.6, "Zen Technologies"),
    (8.6, "The Fertilisers and Chemicals"),
    (8.52, "Anupam Rasayan"),
    (8.49, "CreditAccess Grameen"),
    (8.43, "Aster DM Healthcare"),
    (8.42, "ABB"),
    (8.42, "Honasa Consumer"),
    (8.39, "Aarti Industries"),
    (8.39, "Dr. Lal Pathlabs"),
    (8.36, "Zydus Wellness"),
    (8.32, "Ipca Laboratories"),
    (8.32, "Cholamandalam"),
    (8.3, "Asian Paints"),
    (8.28, "Gland Pharma"),
    (8.23, "Aurobindo Pharma"),
    (8.22, "Tata Capital"),
    (7.85, "Delhivery"),
    (7.82, "Granules"),
    (7.77, "Dr. Reddy's Labs"),
    (7.74, "Computer Age Mgmt"),
    (7.68, "Bharat Heavy Electricals"),
    (7.67, "Adani Energy"),
    (7.51, "Solar Industries"),
    (7.37, "Ather Energy"),
    (7.35, "JSW Energy"),
    (7.32, "Tata Communications"),
    (7.31, "Bajaj Auto"),
    (7.31, "Hitachi Energy"),
    (7.23, "Coal India"),
    (7.11, "Lloyds Metals & Energy"),
    (7.1, "Ajanta Pharma"),
    (7.09, "Premier Energies"),
    (6.72, "Chennai Petroleum"),
    (6.48, "Biocon"),
    (6.47, "Bosch"),
    (6.43, "Gujarat Fluorochemicals"),
    (6.22, "Phoenix Mills"),
    (6.18, "Usha Martin"),
    (6.06, "Nestle"),
    (6.06, "Schaeffler"),
    (5.98, "Laurus Labs"),
    (5.98, "IFCI"),
    (5.97, "Aditya Birla Sun Life AMC"),
    (5.92, "Thermax"),
    (5.84, "Cemindia Projects"),
    (5.77, "Divi's Laboratories"),
    (5.76, "Shyam Metalics"),
    (5.73, "Torrent Pharma"),
    (5.73, "AIA Engineering"),
    (5.7, "Emcure Pharma"),
    (5.47, "Finolex Cables"),
    (5.44, "AU SF Bank"),
    (5.38, "Siemens"),
    (5.32, "Elgi Equipments"),
    (5.27, "Minda Corporation"),
    (5.23, "L&T"),
    (5.22, "Zydus Lifesciences"),
    (5.16, "Marico"),
    (5.11, "Adani Green Energy"),
    (5.11, "Titagarh Rail Systems"),
    (5.02, "Sun Pharmaceutical"),
    (4.88, "Titan Company"),
    (4.75, "Axis Bank"),
    (4.61, "Siemens Energy"),
    (4.59, "Caplin Point Labs"),
    (4.54, "J B Chemicals"),
    (4.48, "Manappuram Finance"),
    (4.45, "Tube Investments"),
    (4.42, "Timken"),
    (4.39, "Samvardhana Motherson"),
    (4.38, "Cummins"),
    (4.31, "Anand Rathi Wealth"),
    (4.06, "Welspun Living"),
    (3.92, "Leela Palaces Hotels Resorts"),
    (3.8, "Vardhman Textiles"),
    (3.72, "Piramal Finance"),
    (3.53, "Adani Enterprises"),
    (3.37, "Jindal Saw"),
    (3.37, "IndusInd Bank"),
    (3.3, "Sona BLW Precision"),
    (3.23, "R R Kabel"),
    (3.17, "Capri Global Capital"),
    (3.09, "Carborundum Universal"),
    (3.07, "JSW Steel"),
    (2.96, "MMTC"),
    (2.9, "Radico Khaitan"),
    (2.75, "Syrma SGS Technology"),
    (2.75, "Belrise Industries"),
    (2.74, "Vodafone Idea"),
    (2.51, "Netweb Technologies"),
    (2.49, "Emmvee Photovoltaic Power"),
    (2.47, "Sai Life Science"),
    (2.46, "Craftsman Automation"),
    (2.41, "Navin Fluorine"),
    (2.29, "Welspun Corp"),
    (2.28, "Apollo Hospitals"),
    (2.26, "Apar Industries"),
    (2.11, "Varun Beverages"),
    (2.09, "Angel One"),
    (2.0, "Bandhan Bank"),
    (1.8, "Krishna Institute"),
    (1.63, "FSN E-Commerce"),
    (1.6, "Himadri Speciality"),
    (1.59, "RBL Bank"),
    (1.57, "Adani Ports"),
    (1.55, "Grasim Industries"),
    (1.49, "Kalpataru Projects"),
    (1.37, "YES Bank"),
    (1.33, "Tata Technologies"),
    (1.33, "GE T&D"),
    (1.21, "Kirloskar Oil Engines"),
    (1.07, "GMR Airports"),
    (1.05, "Bank of Maharashtra"),
    (0.93, "Aditya Birla Capital"),
    (0.89, "Aegis Logistics"),
    (0.61, "Polycab"),
    (0.55, "Pidilite Industries"),
    (0.52, "Data Patterns"),
    (0.52, "KEI Industries"),
    (0.51, "Jammu & Kashmir Bank"),
    (0.49, "Nuvama Wealth"),
    (0.46, "Bharat Forge"),
    (0.41, "Nippon Life Asset Mgmt"),
    (0.28, "Federal Bank"),
    (0.19, "CG Power & Industrial"),
]

ALIAS = {  # TL display name -> our NSE symbol (only the ones normalization can't catch)
    "computer age mgmt": "CAMS",
    "au sf bank": "AUBANK",
    "l&t": "LT",
    "cholamandalam": "CHOLAFIN",
    "bharat heavy electricals": "BHEL",
    "adani energy": "ADANIENSOL",
    "bajaj auto": "BAJAJ-AUTO",
    "j b chemicals": "JBCHEPHARM",
    "caplin point labs": "CAPLIPOINT",
    "samvardhana motherson": "MOTHERSON",
    "tube investments": "TIINDIA",
    "anand rathi wealth": "ANANDRATHI",
    "welspun living": "WELSPUNLIV",
    "leela palaces hotels resorts": "THELEELA",
    "vardhman textiles": "VTL",
    "piramal finance": "PIRAMALFIN",
    "sona blw precision": "SONACOMS",
    "r r kabel": "RRKABEL",
    "capri global capital": "CGCL",
    "carborundum universal": "CARBORUNIV",
    "radico khaitan": "RADICO",
    "syrma sgs technology": "SYRMA",
    "vodafone idea": "IDEA",
    "emmvee photovoltaic power": "EMMVEE",
    "sai life science": "SAILIFE",
    "navin fluorine": "NAVINFLUOR",
    "welspun corp": "WELCORP",
    "varun beverages": "VBL",
    "angel one": "ANGELONE",
    "bandhan bank": "BANDHANBNK",
    "krishna institute": "KIMS",
    "fsn e-commerce": "NYKAA",
    "himadri speciality": "HSCL",
    "grasim industries": "GRASIM",
    "kalpataru projects": "KPIL",
    "tata technologies": "TATATECH",
    "ge t&d": "GVT&D",
    "kirloskar oil engines": "KIRLOSENG",
    "gmr airports": "GMRAIRPORT",
    "bank of maharashtra": "MAHABANK",
    "aditya birla capital": "ABCAPITAL",
    "aegis logistics": "AEGISLOG",
    "data patterns": "DATAPATTNS",
    "kei industries": "KEI",
    "jammu & kashmir bank": "J&KBANK",
    "nuvama wealth": "NUVAMA",
    "nippon life asset mgmt": "NAM-INDIA",
    "cg power & industrial": "CGPOWER",
    "aditya birla sun life amc": "ABSLAMC",
    "allied blenders": "ABDL",
    "the fertilisers and chemicals": "FACT",
    "anupam rasayan": "ANUPAMRAS",
    "creditaccess grameen": "CREDITACC",
    "aster dm healthcare": "ASTERDM",
    "honasa consumer": "HONASA",
    "dr. lal pathlabs": "LALPATHLAB",
    "zydus wellness": "ZYDUSWELL",
    "tata capital": "TATACAP",
    "solar industries": "SOLARINDS",
    "ather energy": "ATHERENERG",
    "lloyds metals & energy": "LLOYDSME",
    "gujarat fluorochemicals": "FLUOROCHEM",
    "cemindia projects": "ANTHEM",
    "shyam metalics": "SHYAMMETL",
    "torrent pharma": "TORNTPHARM",
    "finolex cables": "FINCABLES",
    "elgi equipments": "ELGIEQUIP",
    "minda corporation": "MINDACORP",
    "zydus lifesciences": "ZYDUSLIFE",
    "titagarh rail systems": "TITAGARH",
    "titan company": "TITAN",
    "siemens energy": "SIEMENSEN",
    "manappuram finance": "MANAPPURAM",
    "jsw steel": "JSWSTEEL",
    "netweb technologies": "NETWEB",
    "belrise industries": "BELRISE",
    "craftsman automation": "CRAFTSMAN",
    "apollo hospitals": "APOLLOHOSP",
    "apar industries": "APARINDS",
    "jindal saw": "JINDALSAW",
    "indusind bank": "INDUSINDBK",
    "rbl bank": "RBLBANK",
    "adani ports": "ADANIPORTS",
    "yes bank": "YESBANK",
    "polycab": "POLYCAB",
    "pidilite industries": "PIDILITIND",
    "bharat forge": "BHARATFORG",
    "federal bank": "FEDERALBNK",
    "hitachi energy": "POWERINDIA",
    "icici prudential asset": "ICICIAMC",
    "lg electronics": "LGEIL",
    "lenskart solutions": "LENSKART",
    "aditya infotech": "CPPLUS",
    "niva bupa health insurance": "NIVABUPA",
    "travel food services": "TRAVELFOOD",
    "star health": "STARHEALTH",
    "vijaya diagnostic centre": "VIJAYA",
    "acme solar holdings": "ACMESOLAR",
    "sammaan capital": "SAMMAANCAP",
    "premier energies": "PREMIERENE",
    "chennai petroleum": "CHENNPETRO",
    "usha martin": "USHAMART",
    "zf commercial": "ZFCVINDIA",
    "eicher motors": "EICHERMOT",
    "delhivery": "DELHIVERY",
    "nmdc": "NMDC",
    "hfcl": "HFCL",
    "abb": "ABB",
    "biocon": "BIOCON",
    "bosch": "BOSCHLTD",
    "nestle": "NESTLEIND",
    "ifci": "IFCI",
    "thermax": "THERMAX",
    "siemens": "SIEMENS",
    "marico": "MARICO",
    "timken": "TIMKEN",
    "cummins": "CUMMINSIND",
    "mmtc": "MMTC",
    "lupin": "LUPIN",
    "granules": "GRANULES",
    "schaeffler": "SCHAEFFLER",
    "laurus labs": "LAURUSLABS",
    "ajanta pharma": "AJANTPHARM",
    "ipca laboratories": "IPCALAB",
    "aurobindo pharma": "AUROPHARMA",
    "gland pharma": "GLAND",
    "sun pharmaceutical": "SUNPHARMA",
    "divi's laboratories": "DIVISLAB",
    "emcure pharma": "EMCURE",
    "dr. reddy's labs": "DRREDDY",
    "asian paints": "ASIANPAINT",
    "axis bank": "AXISBANK",
    "exide industries": "EXIDEIND",
    "ccl products": "CCL",
    "can fin homes": "CANFINHOME",
    "shriram finance": "SHRIRAMFIN",
    "engineers india": "ENGINERSIN",
    "zen technologies": "ZENTEC",
    "aarti industries": "AARTIIND",
    "coal india": "COALINDIA",
    "tata communications": "TATACOMM",
    "phoenix mills": "PHOENIXLTD",
    "jsw energy": "JSWENERGY",
    "aia engineering": "AIAENG",
    "adani green energy": "ADANIGREEN",
    "adani enterprises": "ADANIENT",
}


def norm(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9& ]", "", s)
    for _w in [" limited", " ltd", " industries", " corporation", " company", " india", " motors"]:
        pass
    return re.sub(r"\s+", "", s)


# build meta name -> sym
NAME2SYM = {}
for sym, m in META.items():
    nm = m.get("name", "")
    for cand in (norm(sym), norm(nm)):
        if cand and cand not in NAME2SYM:
            NAME2SYM[cand] = sym


def resolve(name):
    n = name.lower().strip()
    if n in ALIAS:
        return ALIAS[n]
    k = norm(name)
    if k in NAME2SYM:
        return NAME2SYM[k]
    return None


tl_syms = []
unresolved = []
for d, nm in TL:
    s = resolve(nm)
    if s:
        tl_syms.append((s, d, nm))
    else:
        unresolved.append(nm)
TLS = {s for s, _, _ in tl_syms}


def inuniv(s):
    return s in data and data[s].get("d")  # we have price data for it


matched = sorted(TLS & OUR)
tl_only = [(s, d, nm) for s, d, nm in tl_syms if s not in OUR]
our_only = sorted(OUR - TLS)

print("TL live=%d names, resolved to %d syms (%d unresolved)" % (len(TL), len(TLS), len(unresolved)))
print("OUR 2026-06-12=%d syms" % len(OUR))
print("\nMATCH (in both): %d" % len(matched))
print("  ", ", ".join(matched))
print("\nTL has, OURS missing: %d" % len(tl_only))
for s, d, nm in sorted(tl_only, key=lambda x: -x[1]):
    print("   %-12s %5.2f%%  %-28s indata=%s" % (s, d, nm, bool(inuniv(s))))
print("\nOURS has, TL missing: %d" % len(our_only))
print("  ", ", ".join(our_only))
print("\nUNRESOLVED TL names:", unresolved)
