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


import json
import os
from datetime import UTC, datetime

LANDING_PATH = "/Volumes/stock_research/landing/raw_landing/companies"

WATCHLIST = [
    {
        "ticker": "RELIANCE.NS",
        "company_name": "Reliance Industries Ltd",
        "sector": "Energy / Conglomerate",
        "profile": "Diversified conglomerate spanning oil-to-chemicals (refining, petrochemicals), retail (Reliance Retail, India's largest retailer by revenue), and digital services (Jio telecom and digital platforms), with growing media and financial services ambitions. Promoter-controlled by the Ambani family; among the largest companies by market cap on NSE/BSE.",
    },
    {
        "ticker": "TCS.NS",
        "company_name": "Tata Consultancy Services Ltd",
        "sector": "IT Services",
        "profile": "India's largest IT services company by revenue, part of the Tata Group. Provides IT consulting, application development, and business process services across banking/financial services, retail, and manufacturing, with a large US/Europe client base. Widely treated as a bellwether for Indian IT sector sentiment.",
    },
    {
        "ticker": "INFY.NS",
        "company_name": "Infosys Ltd",
        "sector": "IT Services",
        "profile": "Second-largest Indian IT services company, focused on digital transformation, cloud, and consulting services. Known for strong corporate governance; an early Indian IT bellwether alongside TCS, with heavy exposure to US/European enterprise clients.",
    },
    {
        "ticker": "HDFCBANK.NS",
        "company_name": "HDFC Bank Ltd",
        "sector": "Banking",
        "profile": "India's largest private-sector bank by assets, following its 2023 merger with HDFC Ltd (housing finance). Strong retail banking franchise across deposits, retail loans, and credit cards, plus corporate banking and a large mortgage book inherited from the merger.",
    },
    {
        "ticker": "ICICIBANK.NS",
        "company_name": "ICICI Bank Ltd",
        "sector": "Banking",
        "profile": "One of India's largest private-sector banks, with a diversified retail and corporate lending book, plus significant presence in insurance and asset management through group subsidiaries.",
    },
    {
        "ticker": "BHARTIARTL.NS",
        "company_name": "Bharti Airtel Ltd",
        "sector": "Telecom",
        "profile": "India's second-largest telecom operator by subscribers (behind Reliance Jio), with significant African telecom operations via Airtel Africa. Key player in 5G rollout and mobile data monetization in India.",
    },
    {
        "ticker": "ITC.NS",
        "company_name": "ITC Ltd",
        "sector": "FMCG / Conglomerate",
        "profile": "Diversified conglomerate historically anchored in cigarettes/tobacco (still the largest profit contributor), with growing FMCG (foods, personal care), paperboard/packaging, and agri-business segments. Frequently discussed for restructuring narratives, including its completed hotels demerger.",
    },
    {
        "ticker": "LT.NS",
        "company_name": "Larsen & Toubro Ltd",
        "sector": "Engineering & Construction",
        "profile": "India's largest engineering and construction conglomerate, spanning infrastructure, heavy engineering, defense, and technology (via subsidiaries LTIMindtree and LTTS). Widely watched as a bellwether for India's capex/infrastructure investment cycle.",
    },
    {
        "ticker": "SBIN.NS",
        "company_name": "State Bank of India",
        "sector": "Banking",
        "profile": "India's largest public-sector bank by assets, with the widest branch/ATM network in the country. Dominant in government-linked lending and retail deposits, with multiple listed subsidiaries including SBI Life and SBI Cards.",
    },
    {
        "ticker": "HINDUNILVR.NS",
        "company_name": "Hindustan Unilever Ltd",
        "sector": "FMCG",
        "profile": "India's largest FMCG company, a subsidiary of Unilever plc. Portfolio spans home care, personal care, foods, and refreshment brands, with deep rural and urban distribution reach.",
    },
    {
        "ticker": "MARUTI.NS",
        "company_name": "Maruti Suzuki India Ltd",
        "sector": "Automobiles",
        "profile": "India's largest passenger vehicle manufacturer by volume, majority-owned by Suzuki Motor Corporation of Japan. Dominant in small/mid-size cars, increasingly investing in CNG and hybrid/EV models amid shifting emissions norms and competition.",
    },
    {
        "ticker": "SUNPHARMA.NS",
        "company_name": "Sun Pharmaceutical Industries Ltd",
        "sector": "Pharmaceuticals",
        "profile": "India's largest pharmaceutical company by revenue, with a significant US generics business plus a branded/specialty portfolio (dermatology, ophthalmology) and emerging markets presence.",
    },
    {
        "ticker": "TMPV.NS",
        "company_name": "Tata Motors Passenger Vehicles Ltd",
        "sector": "Automobiles",
        "profile": "Part of the Tata Group, spun off from Tata Motors Ltd in the October 2025 demerger, retaining the passenger vehicle, EV, and Jaguar Land Rover (JLR) businesses — JLR remains the dominant share of revenue. The original commercial-vehicle business continues separately as TML Commercial Vehicles Ltd (TMCV.NS).",
    },
    {
        "ticker": "ASIANPAINT.NS",
        "company_name": "Asian Paints Ltd",
        "sector": "Consumer / Paints",
        "profile": "India's largest paint company, dominant in decorative paints with a growing presence in home décor and waterproofing adjacent categories. Historically strong pricing power and distribution moat, facing increased competition from new entrants.",
    },
    {
        "ticker": "AXISBANK.NS",
        "company_name": "Axis Bank Ltd",
        "sector": "Banking",
        "profile": "India's third-largest private-sector bank, with a diversified corporate, SME, and retail lending book. Expanded significantly via its 2023 acquisition of Citibank's India consumer banking business.",
    },
]


def main():
    os.makedirs(LANDING_PATH, exist_ok=True)
    for rec in WATCHLIST:
        payload = {**rec, "exchange": "NSE", "ingested_at": datetime.now(UTC).isoformat()}
        path = f"{LANDING_PATH}/{rec['ticker'].replace('.', '_')}.json"
        with open(path, "w") as f:
            json.dump(payload, f)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
