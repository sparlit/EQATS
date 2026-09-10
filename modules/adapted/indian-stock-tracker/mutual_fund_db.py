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


"""
Script to fetch mutual fund data from TigZig MF NAV API and store in a separate SQLite database.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import requests
from models import Base, MutualFundAsset, MutualFundSuggestion, get_mutual_fund_engine, get_mutual_fund_session

# Freshness thresholds (in days)
# Small/Mid cap funds may be newer, so we're more lenient
MAX_FUND_AGE_DAYS = 365  # Fund must have NAV within last 1 year (was 2)
MAX_NO_RECENT_DATA_DAYS = 730  # Fund must have at least some recent NAV data (was 1)

BASE_URL = "https://api.tigzig.com/mf/v1"

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

TOP_N = 45  # Target: 30+ but below 50 funds per category
MAX_WORKERS = 2  # TigZig API allows only ~2 concurrent requests
REQUEST_DELAY = 0.3  # Delay between NAV fetches to avoid rate limiting (reduced from 0.5)

CATEGORIES = {"large_cap": "Large Cap", "mid_cap": "Mid Cap", "small_cap": "Small Cap", "debt": "Debt"}

# Debt sub-categories to include (for reaching 30+ funds)
DEBT_SUB_CATEGORIES = [
    "Banking and PSU Debt Fund",
    "Banking and PSU Fund",
    "Corporate Bond Fund",
    "Credit Risk Fund",
    "Dynamic Bond",
    "Floater Fund",
    "Floating Interest Rates Fund",
    "Gilt Fund",
    "Gilt Fund with 10 year constant duration",
    "Liquid Fund",
    "Long Duration Fund",
    "Low Duration Fund",
    "Medium Duration Fund",
    "Medium to Long Duration Fund",
    "Money Market Fund",
    "Overnight Fund",
    "Short Duration Fund",
    "Ultra Short Duration Fund",
]

# TigZig search category names for each fund category
SEARCH_CATEGORY_NAMES = {
    "large_cap": "Large Cap",
    "mid_cap": "Mid Cap",
    "small_cap": "Small Cap",
    "debt": None,  # Debt uses sub-categories instead
}


# ---------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------

session = requests.Session()


def get_json(url, retries=3, base_delay=1):
    """Make a GET request with retry logic and rate limit handling."""
    for attempt in range(retries):
        try:
            # Add delay between requests to avoid rate limiting
            if hasattr(get_json, "last_request_time"):
                elapsed = time.time() - get_json.last_request_time
                if elapsed < REQUEST_DELAY:
                    time.sleep(REQUEST_DELAY - elapsed)

            response = session.get(url, timeout=30)
            get_json.last_request_time = time.time()

            if response.status_code == 429:
                # Rate limited - check for Retry-After header
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = int(retry_after)
                    except ValueError:
                        delay = base_delay * (2**attempt)  # exponential backoff
                else:
                    delay = base_delay * (2**attempt)  # exponential backoff

                print(f"Rate limited (429). Waiting {delay}s... (attempt {attempt + 1}/{retries})")
                time.sleep(delay)
                continue  # retry

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                print(f"Failed after {retries} attempts: {url} -> {e}")
                return None
            delay = base_delay * (2**attempt)  # exponential backoff
            print(f"Request failed (attempt {attempt + 1}/{retries}): {e}. Retrying in {delay}s...")
            time.sleep(delay)

    return None


# ---------------------------------------------------------
# Filter Direct Growth funds
# ---------------------------------------------------------


def is_direct_growth(name):
    name = name.upper()

    return "DIRECT" in name and "GROWTH" in name and "IDCW" not in name and "DIVIDEND" not in name


# ---------------------------------------------------------
# Check if fund is recent/investable
# ---------------------------------------------------------


def is_fund_recent(nav_data):
    """Check if a mutual fund is recent/investable based on NAV history."""
    if not nav_data:
        return False

    today = date.today()
    fund_age_cutoff = today - timedelta(days=MAX_FUND_AGE_DAYS)
    recent_data_cutoff = today - timedelta(days=MAX_NO_RECENT_DATA_DAYS)

    latest_nav_date = None
    has_recent_data = False

    for record in nav_data:
        # Skip records without date
        if "date" not in record or not record["date"]:
            continue

        try:
            # Parse date in YYYY-MM-DD format (TigZig standard)
            year, month, day = map(int, record["date"].split("-"))
            nav_date = date(year, month, day)
        except (ValueError, AttributeError):
            # Skip malformed dates
            continue

        # Track the latest NAV date
        if latest_nav_date is None or nav_date > latest_nav_date:
            latest_nav_date = nav_date

        # Check if this NAV is within the recent data window
        if nav_date >= recent_data_cutoff:
            has_recent_data = True

    # Must have a valid latest NAV date
    if latest_nav_date is None:
        return False

    # Check if latest NAV is within fund age threshold
    if latest_nav_date < fund_age_cutoff:
        return False

    # Must have at least one NAV in the recent data window
    if not has_recent_data:
        return False

    return True


# ---------------------------------------------------------
# Determine category
# ---------------------------------------------------------

# Mapping of TigZig category_sub values to internal category keys
DEBT_CATEGORY_MAPPING = {
    # Direct debt sub-categories from TigZig API
    "Banking and PSU Debt Fund": "debt",
    "Banking and PSU Fund": "debt",
    "Corporate Bond Fund": "debt",
    "Credit Risk Fund": "debt",
    "Dynamic Bond": "debt",
    "Floater Fund": "debt",
    "Floating Interest Rates Fund": "debt",
    "Gilt Fund": "debt",
    "Gilt Fund with 10 year constant duration": "debt",
    "Liquid Fund": "debt",
    "Long Duration Fund": "debt",
    "Low Duration Fund": "debt",
    "Medium Duration Fund": "debt",
    "Medium to Long Duration Fund": "debt",
    "Money Market Fund": "debt",
    "Overnight Fund": "debt",
    "Short Duration Fund": "debt",
    "Ultra Short Duration Fund": "debt",
    # Also map general "debt" category
    "Debt Funds": "debt",
}

# Mapping of equity category_sub values to internal category keys
EQUITY_CATEGORY_MAPPING = {
    "Large Cap Fund": "large_cap",
    "Mid Cap Fund": "mid_cap",
    "Small Cap Fund": "small_cap",
    "Large & Mid Cap Fund": "mid_cap",
    "Equity Scheme - Large Cap Fund": "large_cap",
}


def get_category(meta_category):
    if not meta_category:
        return None

    category = meta_category.lower()

    if "large cap" in category:
        return "large_cap"

    if "mid cap" in category:
        return "mid_cap"

    if "small cap" in category:
        return "small_cap"

    # Use explicit mapping for debt sub-categories (since they don't contain "debt")
    if meta_category in DEBT_CATEGORY_MAPPING:
        return "debt"

    # Extended categories
    if "flexi cap" in category:
        return "large_cap"
    if "elss" in category:
        return "large_cap"

    return None


# ---------------------------------------------------------
# Fetch NAV history from TigZig API
# ---------------------------------------------------------


def get_nav_history(scheme_code):
    """Fetch NAV history for a scheme using TigZig API.

    The NAV endpoint returns ``scheme_name``, ``first_available_date``,
    ``latest_available_date`` plus the full NAV ``data`` array.
    ``fund_house`` and ``category_sub`` are *not* included by this endpoint
    — callers that need them should use ``get_scheme_metadata``.
    """
    # TigZig accepts AMFI numeric codes (4-7 digits) or 12-char ISINs
    url = f"{BASE_URL}/nav?scheme={scheme_code}"

    data = get_json(url)

    if not data:
        return None

    nav_data = data.get("data", [])

    if not nav_data:
        return None

    return {
        "meta": {
            "scheme_name": data.get("scheme_name", ""),
            "fund_house": data.get("fund_house", ""),
            "scheme_category": data.get("category_sub", ""),
        },
        "data": nav_data,
    }


# ---------------------------------------------------------
# Get scheme metadata (category, fund house) from TigZig
# ---------------------------------------------------------


def get_scheme_metadata(scheme_code):
    """Fetch ``category_sub`` and ``fund_house`` for a scheme.

    The TigZig ``/nav`` endpoint does **not** return these two fields, so we
    fall back to the ``/search`` endpoint.  Because ``/search`` accepts a free
    text query, we pass the scheme name that we already have, then match by
    ``scheme_code``.
    """
    # We need the scheme name to search — re-use the NAV call (cheap)
    url = f"{BASE_URL}/nav?scheme={scheme_code}"
    data = get_json(url)

    if data and data.get("scheme_name"):
        scheme_name = data["scheme_name"]
        # Strip the plan-type suffix to get a searchable core name
        search_q = scheme_name.replace(" - Direct Plan - Growth", "").replace(" - Regular Plan - Growth", "").strip()
        url = f"{BASE_URL}/search?q={requests.utils.quote(search_q)}"
        search_data = get_json(url)
        if search_data:
            for result in search_data.get("results", []):
                if result.get("scheme_code") == scheme_code:
                    return {
                        "fund_house": result.get("fund_house", ""),
                        "category_sub": result.get("category_sub", ""),
                    }
    return {"fund_house": "", "category_sub": ""}


# ---------------------------------------------------------
# Convert NAV history into DataFrame
# ---------------------------------------------------------


def nav_dataframe(nav_data):

    df = pd.DataFrame(nav_data)

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")

    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")

    df = df.dropna(subset=["date", "nav"])

    return df.sort_values("date")


# ---------------------------------------------------------
# Get NAV closest to requested date
# ---------------------------------------------------------


def get_nav_at_date(df, target_date):

    if df.empty:
        return None

    target_date = pd.Timestamp(target_date)

    eligible = df[df["date"] <= target_date]

    if eligible.empty:
        return None

    return eligible.iloc[-1]["nav"]


# ---------------------------------------------------------
# Calculate returns
# ---------------------------------------------------------


def calculate_returns(nav_data):

    df = nav_dataframe(nav_data)

    if df.empty:
        return None

    latest_date = df["date"].max()
    latest_nav = df.loc[df["date"] == latest_date, "nav"].iloc[-1]

    result = {"latest_nav": latest_nav, "latest_date": latest_date}

    # 1 Year
    nav_1y = get_nav_at_date(df, latest_date - pd.DateOffset(years=1))

    if nav_1y:
        result["return_1y"] = ((latest_nav / nav_1y) - 1) * 100
    else:
        result["return_1y"] = None

    # 3 Year CAGR
    nav_3y = get_nav_at_date(df, latest_date - pd.DateOffset(years=3))

    if nav_3y:
        result["return_3y"] = ((latest_nav / nav_3y) ** (1 / 3) - 1) * 100
    else:
        result["return_3y"] = None

    # 5 Year CAGR
    nav_5y = get_nav_at_date(df, latest_date - pd.DateOffset(years=5))

    if nav_5y:
        result["return_5y"] = ((latest_nav / nav_5y) ** (1 / 5) - 1) * 100
    else:
        result["return_5y"] = None

    # Calculate volatility
    df["daily_return"] = df["nav"].pct_change()

    volatility = df["daily_return"].std()

    if pd.notna(volatility):
        result["volatility"] = volatility * np.sqrt(252) * 100
    else:
        result["volatility"] = None

    return result


# ---------------------------------------------------------
# Process one fund
# ---------------------------------------------------------


def process_fund(scheme, cached_meta=None):
    """Process a single fund: fetch NAV data, calculate returns, generate score.

    Args:
        scheme: Dict with scheme_code and scheme_name
        cached_meta: Optional pre-fetched metadata dict with fund_house and category_sub

    Returns:
        dict: Processed fund data with returns, or None if invalid
    """
    # Support both formats: schemeCode (uppercase from curated list) and scheme_code (lowercase from API)
    scheme_code = scheme.get("schemeCode") or scheme.get("scheme_code")
    scheme_name = scheme.get("schemeName") or scheme.get("scheme_name") or ""

    if not scheme_code:
        return None

    # Support both int and string scheme codes
    if not isinstance(scheme_code, int):
        try:
            scheme_code = int(scheme_code)
        except (ValueError, TypeError):
            return None

    # Already filtered for Direct Growth in fetch_and_filter_direct_growth
    # but keep check for safety if called with unfiltered data
    if not is_direct_growth(scheme_name):
        return None

    data = get_nav_history(scheme_code)

    if not data:
        return None

    # Check if fund is recent/investable
    if not is_fund_recent(data["data"]):
        return None

    # Get scheme metadata (category, fund house)
    meta = data.get("meta", {})

    # Use cached metadata if available, otherwise fetch from API
    if cached_meta:
        meta.update(
            {
                "scheme_category": cached_meta.get("category_sub", ""),
                "fund_house": cached_meta.get("fund_house", ""),
            }
        )
    else:
        scheme_meta = get_scheme_metadata(scheme_code)
        meta.update(
            {
                "scheme_category": scheme_meta.get("category_sub", ""),
                "fund_house": scheme_meta.get("fund_house", ""),
            }
        )

    category = get_category(meta.get("scheme_category", ""))

    if category is None:
        return None

    returns = calculate_returns(data["data"])

    if not returns:
        return None

    # Convert latest_date to a date object if it is a Timestamp
    latest_nav_date_value = returns.get("latest_date")
    if latest_nav_date_value is not None and hasattr(latest_nav_date_value, "date"):
        latest_nav_date_value = latest_nav_date_value.date()

    return {
        "scheme_code": scheme_code,
        "scheme_name": meta.get("scheme_name"),
        "fund_house": meta.get("fund_house"),
        "category": category,
        "latest_nav_date": latest_nav_date_value,
        **returns,
    }


# ---------------------------------------------------------
# Score funds
# ---------------------------------------------------------


def calculate_score(df):

    # Require minimum historical data - only 1-year return is mandatory
    df = df.dropna(subset=["return_1y"]).copy()

    if df.empty:
        return df

    # Percentile ranking
    df["score_1y"] = df["return_1y"].rank(pct=True) * 100

    # 3-year return - if available, use it; if not, score will be based on 1y only
    if df["return_3y"].notna().sum() > 0:
        df["score_3y"] = df["return_3y"].rank(pct=True) * 100

        # If 5Y exists, use it.
        if df["return_5y"].notna().sum() > 0:
            df["score_5y"] = df["return_5y"].rank(pct=True) * 100

            df["score"] = df["score_1y"] * 0.30 + df["score_3y"] * 0.40 + df["score_5y"].fillna(0) * 0.30

        else:
            df["score"] = df["score_1y"] * 0.40 + df["score_3y"] * 0.60
    else:
        # Only 1-year return available
        df["score"] = df["score_1y"]

    return df


# ---------------------------------------------------------
# Initialize database
# ---------------------------------------------------------


def init_mutual_fund_db():
    """Initialize the mutual funds database."""
    engine = get_mutual_fund_engine()
    Base.metadata.create_all(engine)
    print("Mutual funds database initialized.")


def clear_category_data(category_key=None):
    """Clear existing suggestion and asset data for a category (or all categories)."""
    session = get_mutual_fund_session()
    try:
        if category_key:
            # Clear specific category
            assets = session.query(MutualFundAsset).filter_by(type=category_key).all()
            asset_ids = [a.id for a in assets]
            if asset_ids:
                session.query(MutualFundSuggestion).filter(MutualFundSuggestion.asset_id.in_(asset_ids)).delete(
                    synchronize_session=False
                )
                session.query(MutualFundAsset).filter_by(type=category_key).delete(synchronize_session=False)
            print(f"Cleared existing data for category: {category_key}")
        else:
            # Clear all data
            session.query(MutualFundSuggestion).delete()
            session.query(MutualFundAsset).delete()
            print("Cleared all mutual fund data")
        session.commit()
    except Exception as e:
        print(f"Error clearing data: {e}")
        session.rollback()
    finally:
        session.close()


# ---------------------------------------------------------
# Store fund in database
# ---------------------------------------------------------


def store_fund_in_db(fund_data, category):
    """Store a single fund in the mutual funds database."""
    session = get_mutual_fund_session()
    try:
        # Get score, default to 0 if NaN
        score = fund_data.get("score")
        if pd.isna(score) or score is None:
            score = 0.0
        score = float(score)

        # Check if asset already exists
        existing_asset = session.query(MutualFundAsset).filter_by(scheme_code=fund_data["scheme_code"]).first()

        if not existing_asset:
            # Create new asset
            asset = MutualFundAsset(
                scheme_code=fund_data["scheme_code"],
                scheme_name=fund_data["scheme_name"],
                fund_house=fund_data["fund_house"],
                type=category,
                latest_nav_date=fund_data.get("latest_nav_date"),
            )
            session.add(asset)
            session.flush()  # Get the ID

            # Create suggestion
            suggestion = MutualFundSuggestion(
                asset_id=asset.id,
                date=datetime.now().date(),
                score=score,
                reasoning=f"Top {category.replace('_', ' ').title()} fund based on returns",
            )
            session.add(suggestion)
        else:
            # Update existing asset's suggestion
            latest_suggestion = (
                session.query(MutualFundSuggestion)
                .filter_by(asset_id=existing_asset.id)
                .order_by(MutualFundSuggestion.date.desc())
                .first()
            )

            if latest_suggestion:
                latest_suggestion.score = score
                latest_suggestion.date = datetime.now().date()
            else:
                suggestion = MutualFundSuggestion(
                    asset_id=existing_asset.id,
                    date=datetime.now().date(),
                    score=score,
                    reasoning=f"Top {category.replace('_', ' ').title()} fund based on returns",
                )
                session.add(suggestion)

        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"Error storing fund {fund_data.get('scheme_code')}: {e}")
        return False
    finally:
        session.close()


# ---------------------------------------------------------
# Dynamic API fetching
# ---------------------------------------------------------


def search_schemes(category_filter=None, sub_category=None, limit=100, offset=0, plan="Direct", option="Growth"):
    """Search for mutual fund schemes via TigZig API.

    Args:
        category_filter: Category name (e.g., "Large Cap", "Mid Cap", "Small Cap")
        sub_category: Sub-category filter for debt funds
        limit: Number of results per page (max 100)
        offset: Pagination offset
        plan: Plan filter (default: "Direct")
        option: Option filter (default: "Growth")

    Returns:
        dict: API response with 'total_matches', 'count', 'results'
    """
    base_url = "https://api.tigzig.com/mf/v1/search"
    params = {"limit": limit, "offset": offset}

    if sub_category:
        params["category"] = sub_category
    elif category_filter:
        params["category"] = category_filter

    # Add plan and option filters (TigZig API accepts case-insensitive values)
    if plan:
        params["plan"] = plan
    if option:
        params["option"] = option

    try:
        response = session.get(base_url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error searching schemes: {e}")
        return None


def fetch_all_schemes_for_category(category_key, category_name):
    """Fetch all schemes for a given category using pagination.

    Returns:
        list: List of scheme dictionaries
    """
    all_schemes = []
    limit = 100

    # For debt funds, we need to iterate over sub-categories
    sub_categories_to_fetch = DEBT_SUB_CATEGORIES if category_key == "debt" else [None]

    for sub_cat in sub_categories_to_fetch:
        print(f"  Fetching {'sub-category: ' + sub_cat if sub_cat else category_name}...")
        offset = 0  # Reset offset for each sub-category

        while True:
            result = search_schemes(
                category_filter=category_name if sub_cat is None else None,
                sub_category=sub_cat,
                limit=limit,
                offset=offset,
            )

            if not result:
                break

            total_matches = result.get("total_matches", 0)
            results = result.get("results", [])

            all_schemes.extend(results)
            offset += limit

            if len(results) < limit or offset >= total_matches:
                break

    return all_schemes


def fetch_and_filter_direct_growth(schemes_data):
    """Filter schemes to only include Direct Growth funds.

    Args:
        schemes_data: List of scheme dicts from API

    Returns:
        list: Filtered list of Direct Growth schemes
    """
    direct_growth = []
    seen_codes = set()

    for scheme in schemes_data:
        name = scheme.get("scheme_name", "").upper()
        scheme_code = scheme.get("scheme_code")

        # Deduplicate by scheme_code
        if scheme_code in seen_codes:
            continue
        seen_codes.add(scheme_code)

        # Filter for Direct Growth (case-insensitive)
        if "DIRECT" in name and "GROWTH" in name and "IDCW" not in name and "DIVIDEND" not in name:
            direct_growth.append(scheme)

    return direct_growth


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------


def process_funds_for_category(schemes, category_key, max_funds=None):
    """Process funds for a single category sequentially with rate limiting."""
    if max_funds is None:
        max_funds = TOP_N + 10

    results = []

    for i, scheme in enumerate(schemes):
        if len(results) >= max_funds:
            break

        cached_meta = {"category_sub": scheme.get("category_sub", ""), "fund_house": scheme.get("amc", "")}
        result = process_fund(scheme, cached_meta)

        if result:
            results.append(result)

        # Add delay between requests to avoid rate limiting
        if i < len(schemes) - 1:
            time.sleep(REQUEST_DELAY)

        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(schemes)} schemes, valid: {len(results)}")

    return results


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------


def main():
    # Initialize database
    init_mutual_fund_db()

    # Clear existing data first to avoid duplicates
    clear_category_data()

    all_results = []

    # Process each category separately
    for category_key, category_name in CATEGORIES.items():
        print(f"\n{'=' * 60}")
        print(f"Processing {category_name} funds...")
        print(f"{'=' * 60}")

        # Fetch schemes for this category
        schemes = fetch_all_schemes_for_category(category_key, category_name)
        print(f"  Raw schemes fetched: {len(schemes)}")

        # Filter for Direct Growth only
        direct_growth_schemes = fetch_and_filter_direct_growth(schemes)
        print(f"  Direct Growth funds: {len(direct_growth_schemes)}")

        if not direct_growth_schemes:
            print(f"  No Direct Growth funds found for {category_name}")
            continue

        # Check if we already have enough funds for this category
        from models import MutualFundAsset

        session = get_mutual_fund_session()
        try:
            existing_count = session.query(MutualFundAsset).filter_by(type=category_key).count()
            if existing_count >= 30:
                print(f"  Already have {existing_count} {category_name} funds in DB, skipping")
                continue
        finally:
            session.close()

        # Process funds sequentially with early stopping
        results = process_funds_for_category(direct_growth_schemes, category_key, TOP_N + 10)
        print(f"  Valid funds found: {len(results)}")

        if results:
            all_results.extend(results)

            # Store results immediately for this category
            df_cat = pd.DataFrame(results)
            df_cat = calculate_score(df_cat)
            df_cat = df_cat.sort_values("score", ascending=False).head(TOP_N)

            print(f"  Storing {len(df_cat)} {category_name} funds in database...")

            # Store in database
            stored_count = 0
            for _, fund in df_cat.iterrows():
                fund_data = fund.to_dict()
                fund_data["category"] = category_key
                if store_fund_in_db(fund_data, category_key):
                    stored_count += 1

            print(f"  Stored {stored_count} funds in database for {category_name}")

            # Save CSV
            filename = f"top_{category_key}_funds.csv"
            df_cat.to_csv(filename, index=False)
            print(f"  Saved: {filename}")

    print(f"\n{'=' * 60}")
    print(f"Total valid funds processed across all categories: {len(all_results)}")
    print("Done!")


if __name__ == "__main__":
    main()
