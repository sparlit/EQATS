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


import pandas as pd

# Load MS Industry Groups from CSV
ms_df = pd.read_csv("MSindustryGroupList.csv", index_col=False)
valid_ms_groups = set(ms_df["IndustryGroupName"].tolist())

# Ticker sets from vcp_scanner.py
PSU_BANKS_TICKERS = {
    "SBIN",
    "PNB",
    "BOB",
    "CANBK",
    "UNIONBANK",
    "INDIANB",
    "UCOBANK",
    "BANKBARODA",
    "BANKINDIA",
    "MAHABANK",
    "CENTRALBK",
    "IOB",
    "PSB",
}
PRIVATE_BANKS_TICKERS = {
    "HDFCBANK",
    "ICICIBANK",
    "KOTAKBANK",
    "AXISBANK",
    "INDUSINDBK",
    "FEDERALBNK",
    "IDFCFIRSTB",
    "BANDHANBNK",
    "YESBANK",
    "CUB",
    "KTKBANK",
    "RBLBANK",
    "SOUTHBANK",
    "CSBBANK",
    "AUBANK",
    "INDUSIND",
}
INSURANCE_TICKERS = {
    "HDFCLIFE",
    "SBILIFE",
    "ICICIPRULI",
    "LIC",
    "GICRE",
    "NIACL",
    "MAXFSL",
    "ICICIGI",
    "STARHEALTH",
}
AMC_TICKERS = {"HDFCAMC", "NAM-INDIA", "UTIAMC", "ABSLAMC"}
CAPITAL_MARKETS_TICKERS = {
    "CDSL",
    "BSE",
    "MCX",
    "CAMS",
    "KFINTECH",
    "ANGELONE",
    "ISEC",
    "MUTHOOTOT",
    "5PAISA",
    "ANANDRATHI",
    "GEODJITFSL",
    "MOTILALOFS",
}
CABLES_TICKERS = {"POLYCAB", "KEI", "RRKABEL", "FINCABLES"}
TRANSFORMERS_TICKERS = {"VOLTAMP", "CGPOWER", "TRIL", "TRANSFORM", "SCHNEIDER"}
BEARINGS_TICKERS = {"SKFINDIA", "TIMKEN", "SHAFFLER", "SCHAEFFLER", "HARSHA"}
COMPRESSORS_TICKERS = {"ELGIEQUIP", "KPIL", "KIRLPNU"}
HVAC_TICKERS = {"VOLTAS", "BLUESTARCO", "HITACHIHAM"}
COPPER_TICKERS = {"HINDCOPPER"}
STEEL_TICKERS = {
    "TATASTEEL",
    "JSWSTEEL",
    "SAIL",
    "JSL",
    "JINDALSTEL",
    "KALYANISTEEL",
    "APLAPOLLO",
    "WELCORP",
    "MAHSEAMLES",
}
ALUMINIUM_TICKERS = {"HINDALCO", "NATIONALUM"}
MINING_TICKERS = {"COALINDIA", "NMDC", "GMDC"}
EXPLOSIVES_TICKERS = {"SOLARINDS", "PREMEXPLN"}
DYES_PIGMENTS_TICKERS = {"BODALCHEM", "KIRIINDUS", "SUDARSCHEM", "MEGH"}
GAS_TRADING_TICKERS = {"GAIL", "GSPL"}
CGD_TICKERS = {"IGL", "MGL", "ATGL", "GUJGASLTD"}
SOLAR_TICKERS = {"TATAPOWER", "ADANIGREEN", "SWSOLAR", "WAAREEENER", "WEBSOL"}
POWER_EQUIP_TICKERS = {"BHEL", "SUZLON", "INOXWIND", "GET&D"}
CDMO_TICKERS = {"DIVISLAB", "SYNGENE", "SUVENPHAR", "LAURUSLABS"}
DIAGNOSTICS_TICKERS = {"LALPATHLAB", "METROPOLIS", "THYROCARE", "VIJAYA"}
MEDICAL_DEVICES_TICKERS = {"POLYMED"}
COMMERCIAL_VEH_TICKERS = {"ASHOKLEY", "SMLISUZU"}
PASSENGER_VEH_TICKERS = {"MARUTI", "M&M", "TATAMOTORS", "HYUNDAI"}
TYRES_TICKERS = {"MRF", "APOLLOTYRE", "CEATLTD", "JKTYRE", "BALKRISIND"}
EV_COMPONENTS_TICKERS = {"SONACOMS", "MINDACORP", "UNOMINDA"}
BATTERIES_TICKERS = {"EXIDEIND", "AMARAJABAT", "ARE&M"}
TRACTORS_TICKERS = {"ESCORTS", "VSTTILLERS"}
RETAIL_TICKERS = {"TRENT", "DMART", "ABFRL", "SHOPERSTOP", "VMART", "ETHOSLTD"}
JEWELLERY_TICKERS = {"TITAN", "KALYANKJIL", "SENCO", "RAJESHEXPO"}
FOOTWEAR_TICKERS = {"BATAINDIA", "METROBRAND", "RELAXO", "CAMPUS"}
RESTAURANTS_QSR_TICKERS = {"JUBLFOOD", "DEVYANI", "WESTLIFE", "RBA", "SAPPHIRE"}
TEXTILES_TICKERS = {
    "PAGEIND",
    "ARVIND",
    "VTL",
    "RAYMOND",
    "WELSPUNLIV",
    "ALOKIND",
    "GARFIBRES",
    "GOKEX",
    "KPRMILL",
}
AEROSPACE_DEFENCE_TICKERS = {
    "HAL",
    "BEL",
    "BDL",
    "ASTRAMICRO",
    "PARAS",
    "DATAPATTNS",
    "ZENTEC",
    "MTARTECH",
    "DYNAMATECH",
    "IDEAFORGE",
}
SHIPBUILDING_TICKERS = {"MAZDOCK", "COCHINSHIP", "GRSE"}
EMS_TICKERS = {"DIXON", "KAYNES", "SYRMA", "AVALON"}
DATA_CENTERS_TICKERS = {"NETWEB", "ANANTRAJ"}


def get_ms_industry_group(symbol, company, industry):
    sym = symbol.upper().replace(".NS", "")
    comp = company.upper()
    ind = industry.upper()

    # 0. Railways
    railway_tickers = {
        "IRFC",
        "IRCTC",
        "RVNL",
        "IRCON",
        "RITES",
        "TITAGARH",
        "TEXMACO",
        "RAILTEL",
        "JWL",
    }
    if sym in railway_tickers or "RAILWAY" in comp:
        return "Transportation-Rail IN", "Railways"

    # 0.5. Defense / Aerospace
    if sym in AEROSPACE_DEFENCE_TICKERS or any(
        x in comp for x in ["AEROSPACE", "DEFENCE", "DEFENSE", "DYNAMICS"]
    ):
        return "Aerospace/Defense IN", "Defense"

    # 1. Financials
    if "FINANCIAL" in ind or "BANKS" in ind:
        if sym in PSU_BANKS_TICKERS or any(
            x in comp
            for x in [
                "STATE BANK",
                "PUNJAB NATIONAL",
                "BANK OF BARODA",
                "CANARA",
                "UNION BANK",
                "INDIAN BANK",
                "UCO BANK",
                "BANK OF INDIA",
                "MAHARASHTRA",
                "CENTRAL BANK",
                "OVERSEAS",
                "SHUBH",
                "PSU",
            ]
        ):
            return "Banks-Money Center IN", "Banks"
        if sym in PRIVATE_BANKS_TICKERS or any(
            x in comp
            for x in [
                "HDFC BANK",
                "ICICI BANK",
                "KOTAK",
                "AXIS",
                "INDUSIND",
                "FEDERAL",
                "IDFC FIRST",
                "BANDHAN",
                "YES BANK",
                "CITY UNION",
                "KARUR VYSYA",
                "RBL",
                "SOUTH INDIAN",
                "CSB BANK",
                "AU SMALL",
            ]
        ):
            return "Banks-Money Center IN", "Banks"
        if sym in INSURANCE_TICKERS or any(
            x in comp for x in ["INSURANCE", "LIFE", "GENERAL INS", "ASSURANCE", "MAX FINANCIAL"]
        ):
            return "Insurance-Life IN", "NBFCs & Finance"
        if (
            sym in AMC_TICKERS
            or "AMC" in comp
            or "MUTUAL FUND" in comp
            or "ASSET MANAGEMENT" in comp
            or "NIPPON LIFE" in comp
        ):
            return "Finance-Investment Mgmt IN", "NBFCs & Finance"
        if (
            sym in CAPITAL_MARKETS_TICKERS
            or "CAPITAL MARKETS" in ind
            or any(
                x in comp
                for x in [
                    "CDSL",
                    "BSE",
                    "MCX",
                    "CAMS",
                    "KFIN",
                    "ANGEL ONE",
                    "SECURITIES",
                    "WEALTH",
                    "BROKING",
                    "INVESTMENT",
                ]
            )
        ):
            return "Finance-Invest Bnk/Bkrs IN", "NBFCs & Finance"
        return "Finance-Consumer Loans IN", "NBFCs & Finance"

    # 2. Industrials
    if "CAPITAL GOODS" in ind or "INDUSTRIAL" in ind or "MACHINERY" in ind:
        if sym in AEROSPACE_DEFENCE_TICKERS or any(
            x in comp for x in ["AEROSPACE", "DEFENCE", "DEFENSE", "DYNAMICS"]
        ):
            return "Aerospace/Defense IN", "Defense"
        if (
            sym in SHIPBUILDING_TICKERS
            or "SHIPYARD" in comp
            or "SHIPBUILD" in comp
            or "MAZAGON" in comp
        ):
            return "Transportation-Ship IN", "Defense"

        if sym in CABLES_TICKERS or "CABLE" in comp or "RR KABEL" in comp:
            return "Electrical-Power/Equipmt IN", "Capital Goods"
        if sym in TRANSFORMERS_TICKERS or "TRANSFORMER" in comp or "SCHNEIDER" in comp:
            return "Electrical-Power/Equipmt IN", "Capital Goods"
        if sym in BEARINGS_TICKERS or "BEARING" in comp:
            return "Machinery-Gen Industrial IN", "Capital Goods"
        if sym in COMPRESSORS_TICKERS or "COMPRESSOR" in comp or "PNEUMATIC" in comp:
            return "Machinery-Gen Industrial IN", "Capital Goods"
        if sym in HVAC_TICKERS or "VOLTAS" in comp or "BLUE STAR" in comp:
            return "Bldg-A/C &amp; Heating Prds IN", "Capital Goods"
        if "AUTOMATION" in comp or "HONEYWELL" in comp:
            return "Machinery-Gen Industrial IN", "Capital Goods"
        return "Machinery-Gen Industrial IN", "Capital Goods"

    # 3. Materials
    if "METALS & MINING" in ind or "METALS" in ind or "MINING" in ind or "MATERIALS" in ind:
        if sym in COPPER_TICKERS or "COPPER" in comp:
            return "Mining-Metal Ores IN", "Metals & Mining"
        if sym in ALUMINIUM_TICKERS or "ALUMINIUM" in comp or "NALCO" in comp:
            return "Mining-Metal Ores IN", "Metals & Mining"
        if (
            sym in MINING_TICKERS
            or "MINING" in ind
            or "COAL INDIA" in comp
            or "NMDC" in comp
            or "GMDC" in comp
        ):
            return "Mining-Metal Ores IN", "Metals & Mining"
        if (
            sym in STEEL_TICKERS
            or "STEEL" in comp
            or "PIPE" in comp
            or "APOLLO TUBES" in comp
            or "WELSPUN CORP" in comp
        ):
            return "Steel-Producers IN", "Metals & Mining"
        return "Metal Proc &amp; Fabrication IN", "Metals & Mining"

    if "CHEMICALS" in ind:
        agro_keywords = ["AGRICULTURAL", "FERTILIZER", "AGRI"]
        agro_tickers = {"CHAMBLFERT", "FACT", "COROMANDEL", "GNFC", "GSFC", "RCF", "UPL"}
        if any(kw in comp for kw in agro_keywords) or sym in agro_tickers:
            return "Chemicals-Agricultural IN", "Agrochemicals & Fertilizers"
        if sym in EXPLOSIVES_TICKERS or "EXPLOSIVE" in comp or "SOLAR IND" in comp:
            return "Chemicals-Specialty IN", "Specialty Chemicals"
        if (
            sym in DYES_PIGMENTS_TICKERS
            or "DYE" in comp
            or "PIGMENT" in comp
            or "SUDARSHAN" in comp
        ):
            return "Chemicals-Specialty IN", "Specialty Chemicals"
        return "Chemicals-Specialty IN", "Specialty Chemicals"

    # 4. Energy
    if "POWER" in ind or "OIL GAS" in ind or "ENERGY" in ind:
        if sym in GAS_TRADING_TICKERS or "GAIL" in comp or "GSPL" in comp:
            return "Utility-Gas Distribution IN", "Oil Gas & Consumable Fuels"
        if (
            sym in CGD_TICKERS
            or "GUJARAT GAS" in comp
            or "INDRAPRASTHA GAS" in comp
            or "MAHANAGAR GAS" in comp
            or "ADANI TOTAL" in comp
        ):
            return "Utility-Gas Distribution IN", "Oil Gas & Consumable Fuels"
        if sym in SOLAR_TICKERS or "SOLAR" in comp or "ADANI GREEN" in comp or "WAAREE" in comp:
            return "Energy-Solar IN", "Power"
        if (
            sym in POWER_EQUIP_TICKERS
            or "SUZLON" in comp
            or "WIND" in comp
            or "BHEL" in comp
            or "GET&D" in comp
        ):
            return "Electrical-Power/Equipmt IN", "Power"
        return "Energy-Alternative/Other IN", "Power"

    # 5. Healthcare
    if "HEALTHCARE" in ind or "PHARMACEUTICALS" in ind:
        if (
            sym in CDMO_TICKERS
            or "CDMO" in comp
            or "DIVI'S" in comp
            or "SYNGENE" in comp
            or "LAURUS" in comp
        ):
            return "Medical-Biomed/Biotech IN", "Pharma"
        if (
            sym in DIAGNOSTICS_TICKERS
            or "DIAGNOSTIC" in comp
            or "LAL PATH" in comp
            or "METROPOLIS" in comp
        ):
            return "Medical-Services IN", "Hospitals & Healthcare"
        if sym in MEDICAL_DEVICES_TICKERS or "MEDICURE" in comp or "DEVICE" in comp:
            return "Medical-Products IN", "Hospitals & Healthcare"
        if (
            "PHARMA" in comp
            or "LAB" in comp
            or "BIOTECH" in comp
            or "DRUG" in comp
            or "MEDICINE" in comp
        ):
            return "Medical-Generic Drugs IN", "Pharma"
        return "Medical-Hospitals IN", "Hospitals & Healthcare"

    # 6. Auto
    if "AUTO" in ind or "VEHICLE" in ind:
        if sym in TYRES_TICKERS or "TYRE" in comp or "CEAT" in comp or "MRF" in comp:
            return "Auto/Truck-Tires &amp; Misc  IN", "Automobile and Auto Components"
        if sym in EV_COMPONENTS_TICKERS or "EV" in comp or "SONA BLW" in comp or "MINDA" in comp:
            return "Auto/Truck-Original Eqp IN", "Automobile and Auto Components"
        if sym in BATTERIES_TICKERS or "BATTERY" in comp or "EXIDE" in comp or "AMARA RAJA" in comp:
            return "Auto/Truck-Replace Parts IN", "Automobile and Auto Components"
        if sym in TRACTORS_TICKERS or "TRACTOR" in comp or "ESCORT" in comp:
            return "Machinery-Farm IN", "Automobile and Auto Components"
        if sym in COMMERCIAL_VEH_TICKERS or "ASHOK LEYLAND" in comp or "COMMERCIAL VEHICLE" in comp:
            return "Trucks &amp; Parts-Hvy Duty IN", "Automobile and Auto Components"
        return "Auto Manufacturers IN", "Automobile and Auto Components"

    # 7. Consumer
    if "CONSUMER" in ind or "RETAIL" in ind or "TEXTILES" in ind or "SERVICES" in ind:
        if (
            sym in TEXTILES_TICKERS
            or "TEXTILE" in ind
            or "SPINNING" in comp
            or "WEAVING" in comp
            or "PAGE INDUSTRIES" in comp
            or "WELSPUN LIVING" in comp
            or "RAYMOND" in comp
        ):
            return "Apparel-Clothing Mfg IN", "Textiles"
        if (
            sym in RETAIL_TICKERS
            or "RETAIL" in ind
            or "TRENT" in comp
            or "AVENUE SUPERMARTS" in comp
            or "SHOPPERS STOP" in comp
        ):
            if sym == "TRENT":
                return "Retail-Department Stores IN", "Consumer Services"
            if sym == "DMART":
                return "Retail-Super/Mini Mkts IN", "Consumer Services"
            return "Retail-Specialty IN", "Consumer Services"
        if sym in JEWELLERY_TICKERS or "JEWELLER" in comp or "TITAN" in comp or "GOLD" in comp:
            return "Retail/Whlsle-Jewelry IN", "Consumer Durables"
        if (
            sym in FOOTWEAR_TICKERS
            or "FOOTWEAR" in comp
            or "BATA" in comp
            or "METRO BRAND" in comp
            or "RELAXO" in comp
        ):
            return "Apparel-Shoes &amp; Rel Mfg IN", "Consumer Durables"
        if (
            sym in RESTAURANTS_QSR_TICKERS
            or "RESTAURANT" in comp
            or "FOODWORKS" in comp
            or "DEVYANI" in comp
            or "WESTLIFE" in comp
            or "SAPPHIRE" in comp
        ):
            return "Retail-Restaurants IN", "Consumer Services"

    # Emerging defaults
    if sym in AEROSPACE_DEFENCE_TICKERS or any(
        x in comp for x in ["AEROSPACE", "DEFENCE", "DEFENSE", "DYNAMICS"]
    ):
        return "Aerospace/Defense IN", "Defense"
    if sym in EMS_TICKERS or any(x in comp for x in ["EMS", "DIXON", "KAYNES", "SYRMA", "AVALON"]):
        return "Electronic-Parts IN", "Capital Goods"
    if sym in DATA_CENTERS_TICKERS or "DATA CENTER" in comp or "NETWEB" in comp:
        return "Computer-Hardware/Perip IN", "Information Technology"

    # Defaults
    if "TELECOMMUNICATION" in ind:
        return "Telecom Svcs-Wireless IN", "Telecommunication"
    if "INFORMATION TECHNOLOGY" in ind:
        return "Computer-Tech Services IN", "Information Technology"
    if "CONSTRUCTION MATERIALS" in ind:
        return "Bldg-Cement/Concrt/Ag IN", "Construction Materials"
    if "CONSTRUCTION" in ind:
        return "Bldg-Heavy Construction IN", "Construction"
    if "REALTY" in ind:
        return "Real Estate Dvlpmt/Ops IN", "Realty"
    if "MEDIA" in ind or "PUBLICATION" in ind:
        return "Media-Radio/Tv IN", "Media Entertainment & Publication"

    # Direct raw industry defaults to valid MS industry group names
    raw_ind_map = {
        "FAST MOVING CONSUMER GOODS": ("Food-Packaged IN", "Fast Moving Consumer Goods"),
        "CONSUMER SERVICES": ("Retail-Specialty IN", "Consumer Services"),
        "CONSUMER DURABLES": ("Consumer Prod-Electronic IN", "Consumer Durables"),
        "SERVICES": ("Comml Svcs-Consulting IN", "Services"),
        "DIVERSIFIED": ("Diversified Operations IN", "Diversified"),
        "OIL GAS & CONSUMABLE FUELS": (
            "Oil&amp;Gas-Refining/Mktg IN",
            "Oil Gas & Consumable Fuels",
        ),
        "POWER": ("Utility-Electric Power IN", "Power"),
        "TELECOMMUNICATION": ("Telecom Svcs-Wireless IN", "Telecommunication"),
        "INFORMATION TECHNOLOGY": ("Computer-Tech Services IN", "Information Technology"),
        "METALS & MINING": ("Mining-Metal Ores IN", "Metals & Mining"),
        "CHEMICALS": ("Chemicals-Basic IN", "Specialty Chemicals"),
        "HEALTHCARE": ("Medical-Generic Drugs IN", "Pharma"),
        "AUTOMOBILE AND AUTO COMPONENTS": (
            "Auto/Truck-Original Eqp IN",
            "Automobile and Auto Components",
        ),
        "TEXTILES": ("Apparel-Clothing Mfg IN", "Textiles"),
        "REALTY": ("Real Estate Dvlpmt/Ops IN", "Realty"),
        "MEDIA ENTERTAINMENT & PUBLICATION": (
            "Media-Radio/Tv IN",
            "Media Entertainment & Publication",
        ),
        "CONSTRUCTION MATERIALS": ("Bldg-Cement/Concrt/Ag IN", "Construction Materials"),
        "CONSTRUCTION": ("Bldg-Heavy Construction IN", "Construction"),
    }

    if ind in raw_ind_map:
        return raw_ind_map[ind]

    return "Diversified Operations IN", "Diversified"


# Run audit on combined Nifty 500 + MidSmallCap 400
df1 = pd.read_csv("ind_nifty500list.csv")
df2 = pd.read_csv("ind_niftymidsmallcap400list.csv")
df = pd.concat([df1, df2], ignore_index=True)
df["Symbol"] = df["Symbol"].astype(str).str.strip()
df = df.drop_duplicates(subset=["Symbol"])
invalid_mappings = []

for _, row in df.iterrows():
    sym = row["Symbol"]
    company = row["Company Name"]
    industry = row["Industry"]

    ms_group, parent_sec = get_ms_industry_group(sym, company, industry)
    if ms_group not in valid_ms_groups:
        invalid_mappings.append((sym, company, industry, ms_group))

print(f"Total invalid MS mappings: {len(invalid_mappings)}")
for m in invalid_mappings[:10]:
    print(f"Invalid mapping for {m[0]} ({m[1]}): mapped to '{m[3]}' which is not in MS list.")
