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


from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, unique=True, nullable=False)
    name = Column(String)
    exchange = Column(String)  # NSE, BSE, etc.
    sector = Column(String)
    industry = Column(String)
    type = Column(String, nullable=False, default="equity")

    # Fundamental data fields
    market_cap = Column(Float)
    pe_ratio = Column(Float)
    forward_pe = Column(Float)
    eps = Column(Float)
    book_value = Column(Float)
    price_to_book = Column(Float)
    dividend_yield = Column(Float)
    dividend_rate = Column(Float)
    beta = Column(Float)
    profit_margin = Column(Float)
    operating_margin = Column(Float)
    return_on_equity = Column(Float)
    return_on_assets = Column(Float)
    total_revenue = Column(Float)
    total_debt = Column(Float)
    total_cash = Column(Float)
    debt_to_equity = Column(Float)
    shares_outstanding = Column(Float)
    float_shares = Column(Float)
    website = Column(String)
    country = Column(String)
    currency = Column(String)
    last_updated = Column(String)  # timestamp of last data update

    prices = relationship("DailyPrice", back_populates="asset")
    suggestions = relationship("Suggestion", back_populates="asset")


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adj_close = Column(Float)
    volume = Column(Float)
    is_holiday = Column(Boolean, default=False)

    asset = relationship("Asset", back_populates="prices")


class Suggestion(Base):
    __tablename__ = "suggestions"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    score = Column(Float, nullable=False)
    reasoning = Column(String)

    asset = relationship("Asset", back_populates="suggestions")


class MutualFundAsset(Base):
    __tablename__ = "mutual_fund_assets"
    id = Column(Integer, primary_key=True)
    scheme_code = Column(String, unique=True, nullable=False)
    scheme_name = Column(String)
    fund_house = Column(String)
    type = Column(String)  # Will store category like 'large_cap', etc.
    latest_nav_date = Column(Date)  # Date of latest NAV for filtering by freshness

    suggestions = relationship("MutualFundSuggestion", back_populates="asset")


class MutualFundSuggestion(Base):
    __tablename__ = "mutual_fund_suggestions"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("mutual_fund_assets.id"), nullable=False)
    date = Column(Date, nullable=False)
    score = Column(Float, nullable=False)
    reasoning = Column(String)

    asset = relationship("MutualFundAsset", back_populates="suggestions")


class MarketIndexPrice(Base):
    __tablename__ = "market_index_prices"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    interval = Column(String, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    created_at = Column(String)


def get_engine(db_path="sqlite:///stocks.db"):
    return create_engine(db_path, echo=False)


def _add_missing_columns(engine):
    """Add any columns from the Asset/DailyPrice models that are missing from the tables."""
    from sqlalchemy import inspect, text

    # Asset model columns
    asset_existing = (
        {c["name"] for c in inspect(engine).get_columns("assets")} if inspect(engine).has_table("assets") else set()
    )
    asset_columns = {
        "industry": "TEXT",
        "market_cap": "REAL",
        "pe_ratio": "REAL",
        "forward_pe": "REAL",
        "eps": "REAL",
        "book_value": "REAL",
        "price_to_book": "REAL",
        "dividend_yield": "REAL",
        "dividend_rate": "REAL",
        "beta": "REAL",
        "profit_margin": "REAL",
        "operating_margin": "REAL",
        "return_on_equity": "REAL",
        "return_on_assets": "REAL",
        "total_revenue": "REAL",
        "total_debt": "REAL",
        "total_cash": "REAL",
        "debt_to_equity": "REAL",
        "shares_outstanding": "REAL",
        "float_shares": "REAL",
        "website": "TEXT",
        "country": "TEXT",
        "currency": "TEXT",
        "last_updated": "TEXT",
    }

    # DailyPrice model columns
    dp_existing = (
        {c["name"] for c in inspect(engine).get_columns("daily_prices")}
        if inspect(engine).has_table("daily_prices")
        else set()
    )
    dp_columns = {"is_holiday": "BOOLEAN DEFAULT 0"}

    # MarketIndexPrice model columns (for new table)
    mip_existing = (
        {c["name"] for c in inspect(engine).get_columns("market_index_prices")}
        if inspect(engine).has_table("market_index_prices")
        else set()
    )
    mip_columns = {
        "symbol": "TEXT NOT NULL",
        "timestamp": "DATE NOT NULL",
        "interval": "TEXT NOT NULL",
        "open": "REAL",
        "high": "REAL",
        "low": "REAL",
        "close": "REAL",
        "volume": "REAL",
        "created_at": "TEXT",
    }

    with engine.begin() as conn:
        for col_name, col_type in asset_columns.items():
            if col_name not in asset_existing:
                conn.execute(text(f'ALTER TABLE assets ADD COLUMN "{col_name}" {col_type}'))
        for col_name, col_type in dp_columns.items():
            if col_name not in dp_existing:
                conn.execute(text(f'ALTER TABLE daily_prices ADD COLUMN "{col_name}" {col_type}'))
        for col_name, col_type in mip_columns.items():
            if col_name not in mip_existing:
                conn.execute(text(f'ALTER TABLE market_index_prices ADD COLUMN "{col_name}" {col_type}'))

        # Add unique index for MarketIndexPrice table if it doesn't exist
        if inspect(engine).has_table("market_index_prices"):
            # Check if unique index already exists
            indexes = inspect(engine).get_indexes("market_index_prices")
            unique_exists = any(
                idx["unique"] and set(idx["column_names"]) == {"symbol", "timestamp", "interval"} for idx in indexes
            )
            if not unique_exists:
                try:
                    conn.execute(
                        text("""
                        CREATE UNIQUE INDEX idx_market_index_prices_unique
                        ON market_index_prices (symbol, timestamp, interval)
                    """)
                    )
                except Exception:
                    # Index might already exist or there might be a race condition
                    pass


def init_db(db_version: str = "2.0"):
    """Initialize the database with schema version tracking.

    Args:
        db_version: The model/schema version this DB should have.
                    Increment this number whenever model changes are made.
    """
    engine = get_engine()
    # Create all tables first (handles initial schema creation)
    Base.metadata.create_all(engine)
    # Add any missing columns from model updates
    _add_missing_columns(engine)
    _add_missing_mutual_fund_columns(engine)
    # Set schema version
    _set_schema_version(engine, db_version)
    return engine


def get_session():
    engine = get_engine()
    # Ensure schema is up to date before returning a session.
    # This handles the case where an existing database file (e.g. from a
    # previous version or a merged old project) is missing columns that
    # the current models expect.
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    _set_schema_version(engine, "2.0")
    Session = sessionmaker(bind=engine)
    return Session()


def get_mutual_fund_engine(db_path="sqlite:///mutual_funds.db"):
    return create_engine(db_path, echo=False)


def _add_missing_mutual_fund_columns(engine):
    """Add any columns from the MutualFundAsset model that are missing from the table."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if not inspector.has_table("mutual_fund_assets"):
        return

    existing_cols = {c["name"] for c in inspector.get_columns("mutual_fund_assets")}

    model_columns = {
        "latest_nav_date": "DATE",
    }

    with engine.begin() as conn:
        for col_name, col_type in model_columns.items():
            if col_name not in existing_cols:
                conn.execute(text(f'ALTER TABLE mutual_fund_assets ADD COLUMN "{col_name}" {col_type}'))


def get_mutual_fund_session():
    engine = get_mutual_fund_engine()
    # Ensure schema is up to date before returning a session.
    Base.metadata.create_all(engine)
    _add_missing_mutual_fund_columns(engine)
    _set_schema_version(engine, "2.0")
    Session = sessionmaker(bind=engine)
    return Session()


def _get_schema_version(engine) -> str:
    """Get the current schema version from the database, or None if not set."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if not inspector.has_table("schema_version"):
        return None
    try:
        with engine.begin() as conn:
            row = conn.execute(text("SELECT version FROM schema_version")).fetchone()
            return row[0] if row else None
    except Exception:
        return None


def _set_schema_version(engine, version: str):
    """Set the schema version in the database."""
    from sqlalchemy import inspect, text

    # Create table if it doesn't exist
    inspector = inspect(engine)
    if not inspector.has_table("schema_version"):
        with engine.begin() as conn:
            conn.execute(
                text("""
                CREATE TABLE schema_version (
                    id INTEGER PRIMARY KEY,
                    version TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )
            conn.execute(text("INSERT INTO schema_version (version) VALUES (:version)"), {"version": version})
    else:
        # Table exists but may be empty - use MERGE/UPSERT or INSERT/UPDATE
        with engine.begin() as conn:
            # Try UPDATE first, if no rows affected then INSERT
            result = conn.execute(
                text("UPDATE schema_version SET version = :version, updated_at = CURRENT_TIMESTAMP"),
                {"version": version},
            )
            if result.rowcount == 0:
                conn.execute(text("INSERT INTO schema_version (version) VALUES (:version)"), {"version": version})
