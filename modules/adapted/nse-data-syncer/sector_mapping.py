"""
Shared stock -> NSE sector index mapping, used by anything that needs to
compare a stock against its sector's performance (scripts/backtest_swing_setup.py,
scripts/calculate_swing_score.py).

Maps stocks.industry (BSE-style classification, from scripts/update_sectors_from_bse.py)
to a sector index symbol from scripts/sync_dhan_indices.py's DHAN_INDICES.
Many-to-one; industries with no reasonable sector-index equivalent (Packaging,
Sugar, Gems & Jewellery, Trading & Distributors, etc.) are simply omitted -
those stocks are excluded from any sector-dependent screen entirely.
"""
from sqlalchemy import text
import pandas as pd

SECTOR_INDEX_MAP = {
    # Auto
    'Auto Components & Equipments': 'CNXAUTO', 'Passenger Cars & Utility Vehicles': 'CNXAUTO',
    'Tyres & Rubber Products': 'CNXAUTO', '2/3 Wheelers': 'CNXAUTO', 'Tractors': 'CNXAUTO',
    'Commercial Vehicles': 'CNXAUTO',
    # IT
    'Computers - Software & Consulting': 'CNXIT', 'IT Enabled Services': 'CNXIT',
    'Software Products': 'CNXIT', 'Computers Hardware & Equipments': 'CNXIT',
    'Business Process Outsourcing (BPO)/ Knowledge Process Outsourcing (KPO)': 'CNXIT',
    # Pharma / Healthcare
    'Pharmaceuticals': 'CNXPHARMA',
    'Hospital': 'NIFTY_HEALTHCARE', 'Healthcare Research- Analytics & Technology': 'NIFTY_HEALTHCARE',
    'Healthcare Research, Analytics & Technology': 'NIFTY_HEALTHCARE',
    'Healthcare Service Provider': 'NIFTY_HEALTHCARE', 'Biotechnology': 'NIFTY_HEALTHCARE',
    'Pharmacy Retail': 'NIFTY_HEALTHCARE', 'Medical Equipment & Supplies': 'NIFTY_HEALTHCARE',
    # Metal
    'Iron & Steel Products': 'CNXMETAL', 'Iron & Steel': 'CNXMETAL', 'Industrial Minerals': 'CNXMETAL',
    'Aluminium': 'CNXMETAL', 'Copper': 'CNXMETAL', 'Diversified Metals': 'CNXMETAL',
    'Ferro & Silica Manganese': 'CNXMETAL', 'Trading - Metals': 'CNXMETAL', 'Trading - Minerals': 'CNXMETAL',
    'Sponge Iron': 'CNXMETAL', 'Zinc': 'CNXMETAL', 'Aluminium- Copper & Zinc Products': 'CNXMETAL',
    'Aluminium, Copper & Zinc Products': 'CNXMETAL',  # Screener uses ", " where BSE's CSV used "- "
    # Realty / Infra
    'Residential- Commercial Projects': 'CNXREALTY', 'Residential, Commercial Projects': 'CNXREALTY',
    'Civil Construction': 'CNXINFRA', 'Cement & Cement Products': 'CNXINFRA', 'Railway Wagons': 'CNXINFRA',
    'Dredging': 'CNXINFRA', 'Road Assets–Toll- Annuity- Hybrid-Annuity': 'CNXINFRA',
    'Other Construction Materials': 'CNXINFRA',
    # Financial Services / Banks
    'Non Banking Financial Company (NBFC)': 'FINNIFTY', 'Investment Company': 'FINNIFTY',
    'Housing Finance Company': 'FINNIFTY', 'Financial Institution': 'FINNIFTY', 'Other Bank': 'FINNIFTY',
    'Life Insurance': 'FINNIFTY', 'General Insurance': 'FINNIFTY', 'Microfinance Institutions': 'FINNIFTY',
    'Ratings': 'FINNIFTY', 'Financial Products Distributor': 'FINNIFTY', 'Insurance Distributors': 'FINNIFTY',
    'Other Financial Services': 'FINNIFTY', 'Financial Technology (Fintech)': 'FINNIFTY',
    'Private Sector Bank': 'NIFTYPVTBANK', 'Public Sector Bank': 'CNXPSUBANK',
    'Stockbroking & Allied': 'NIFTY_CAPITAL_MKT', 'Asset Management Company': 'NIFTY_CAPITAL_MKT',
    'Depositories- Clearing Houses and Other Intermediaries': 'NIFTY_CAPITAL_MKT',
    'Depositories, Clearing Houses and Other Intermediaries': 'NIFTY_CAPITAL_MKT',
    'Exchange and Data Platform': 'NIFTY_CAPITAL_MKT', 'Financial Data & Stock Exchanges': 'NIFTY_CAPITAL_MKT',
    # FMCG
    'Packaged Foods': 'CNXFMCG', 'Breweries & Distilleries': 'CNXFMCG', 'Personal Care': 'CNXFMCG',
    'Dairy Products': 'CNXFMCG', 'Edible Oil': 'CNXFMCG', 'Diversified FMCG': 'CNXFMCG',
    'Other Food Products': 'CNXFMCG', 'Household Products': 'CNXFMCG', 'Cigarettes & Tobacco Products': 'CNXFMCG',
    'Tea & Coffee': 'CNXFMCG', 'Meat Products including Poultry': 'CNXFMCG', 'Other Beverages': 'CNXFMCG',
    # Energy / Oil & Gas
    'Power Generation': 'CNXENERGY', 'Integrated Power Utilities': 'CNXENERGY', 'Coal': 'CNXENERGY',
    'Power Trading': 'CNXENERGY', 'Power Distribution': 'CNXENERGY', 'Power - Transmission': 'CNXENERGY',
    'Refineries & Marketing': 'NIFTY_OIL_AND_GAS', 'LPG/CNG/PNG/LNG Supplier': 'NIFTY_OIL_AND_GAS',
    'Lubricants': 'NIFTY_OIL_AND_GAS', 'Oil Exploration & Production': 'NIFTY_OIL_AND_GAS',
    'Petrochemicals': 'NIFTY_OIL_AND_GAS', 'Gas Transmission/Marketing': 'NIFTY_OIL_AND_GAS',
    'Trading - Gas': 'NIFTY_OIL_AND_GAS', 'Oil Storage & Transportation': 'NIFTY_OIL_AND_GAS',
    # Consumer Durables
    'Household Appliances': 'CNXCONSRDURBL',
    'Gems- Jewellery And Watches': 'CNXCONSRDURBL', 'Gems, Jewellery And Watches': 'CNXCONSRDURBL',
    'Consumer Electronics': 'CNXCONSRDURBL', 'Ceramics': 'CNXCONSRDURBL', 'Sanitary Ware': 'CNXCONSRDURBL',
    'Furniture- Home Furnishing': 'CNXCONSRDURBL', 'Furniture, Home Furnishing': 'CNXCONSRDURBL',
    'Plastic Products - Consumer': 'CNXCONSRDURBL',
    'Houseware': 'CNXCONSRDURBL', 'Glass - Consumer': 'CNXCONSRDURBL',
    # Media
    'Media & Entertainment': 'CNXMEDIA', 'TV Broadcasting & Software Production': 'CNXMEDIA',
    'Printing & Publication': 'CNXMEDIA', 'Digital Entertainment': 'NIFTY_IND_DIGITAL',
    'Film Production- Distribution & Exhibition': 'CNXMEDIA',
    'Film Production, Distribution & Exhibition': 'CNXMEDIA', 'Print Media': 'CNXMEDIA',
    # Services / Consumption / Tourism
    'Diversified Commercial Services': 'CNXSERVICE', 'Logistics Solution Provider': 'CNXSERVICE',
    'Shipping': 'CNXSERVICE', 'Port & Port services': 'CNXSERVICE', 'Transport Related Services': 'CNXSERVICE',
    'Speciality Retail': 'CNXCONSUMPTION', 'Restaurants': 'CNXCONSUMPTION', 'Diversified Retail': 'CNXCONSUMPTION',
    'Other Consumer Services': 'CNXCONSUMPTION', 'Education': 'CNXCONSUMPTION',
    'Hotels & Resorts': 'NIFTY_IND_TOURISM', 'Tour, Travel Related Services': 'NIFTY_IND_TOURISM',
    'Amusement Parks/ Other Recreation': 'NIFTY_IND_TOURISM', 'Airline': 'NIFTY_IND_TOURISM',
    'Airport & Airport services': 'NIFTY_IND_TOURISM',
    # Digital / New-age
    'E-Retail/ E-Commerce': 'NIFTY_IND_DIGITAL', 'Internet & Catalogue Retail': 'NIFTY_IND_DIGITAL',
    'E-Learning': 'NIFTY_IND_DIGITAL',
    # Defence
    'Aerospace & Defense': 'NIFTY_IND_DEFENCE', 'Ship Building & Allied Services': 'NIFTY_IND_DEFENCE',
}


def load_sector_mapped_universe(session, min_market_cap_cr):
    """Active stocks >= min_market_cap_cr Cr, with a mapped sector index.
    Returns a DataFrame with stock_id, nse_symbol, sector_symbol."""
    min_mcap = min_market_cap_cr * 10_000_000
    rows = session.execute(text("""
        SELECT id, nse_symbol, industry FROM stocks
        WHERE is_active = true AND market_cap >= :min_mcap
    """), {'min_mcap': min_mcap}).fetchall()

    universe = []
    for r in rows:
        sector_symbol = SECTOR_INDEX_MAP.get(r.industry)
        if sector_symbol:
            universe.append({'stock_id': r.id, 'nse_symbol': r.nse_symbol, 'sector_symbol': sector_symbol})
    print(f"Universe: {len(rows)} stocks >= {min_market_cap_cr} Cr, {len(universe)} with a mapped sector "
          f"({len(rows) - len(universe)} excluded - no sector-index mapping).")
    return pd.DataFrame(universe)
