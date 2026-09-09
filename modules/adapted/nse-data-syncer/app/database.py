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


import os
from datetime import datetime, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    create_engine,
    func,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker

# Database URL from environment variable
DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    msg = "DATABASE_URL environment variable is not set."
    raise ValueError(msg)

Base = declarative_base()


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(BigInteger)


class Stock(Base):
    __tablename__ = "stocks"
    id = Column(Integer, primary_key=True)
    nse_symbol = Column(String)
    market_cap = Column(Float)


class DatabaseManager:
    def __init__(self, db_url=DB_URL):
        # Small pool: sync jobs run as short-lived, low-concurrency processes,
        # and up to 5 shards run at once (see daily_sync_optimized.yml). The
        # default pool_size=5/max_overflow=10 let a single shard open up to 15
        # connections, which exhausted RDS's connection limit and caused
        # Prisma on Vercel to time out fetching a connection (P2024).
        self.engine = create_engine(db_url, pool_size=2, max_overflow=0, pool_timeout=30)
        self.Session = sessionmaker(bind=self.engine)

    def get_symbol_map(self):
        """Returns a dictionary mapping NSE symbol to stock_id."""
        session = self.Session()
        try:
            stocks = session.query(Stock.nse_symbol, Stock.id).all()
            return {s.nse_symbol: s.id for s in stocks if s.nse_symbol}
        except SQLAlchemyError as e:
            print(f"Error fetching symbol map: {e}")
            return {}
        finally:
            session.close()

    def insert_stock(self, symbol, details):
        """
        Inserts a new stock into the stocks table.
        Returns the stock_id if successful, None otherwise.
        """
        session = self.Session()
        try:
            # Check if it already exists
            existing_stock = session.execute(
                text("SELECT id FROM stocks WHERE nse_symbol = :symbol"), {"symbol": symbol}
            ).fetchone()

            if existing_stock:
                return existing_stock[0]

            query = text("""
                INSERT INTO stocks (nse_symbol, name, isin, is_active)
                VALUES (:symbol, :name, :isin, true)
                RETURNING id
            """)

            result = session.execute(
                query, {"symbol": symbol, "name": details.get("name"), "isin": details.get("isin")}
            )
            stock_id = result.fetchone()[0]
            session.commit()
            print(f"Inserted new stock: {symbol} (ID: {stock_id})")
            return stock_id
        except Exception as e:
            session.rollback()
            print(f"Error inserting stock {symbol}: {e}")
            return None
        finally:
            session.close()

    def get_last_n_records(self, stock_id, n=5):
        """
        Fetches the last n records for a stock to validate against new data.
        Returns a dict: {date: close_price}
        """
        session = self.Session()
        try:
            query = text("""
                SELECT date, close_price
                FROM daily_prices
                WHERE stock_id = :stock_id
                ORDER BY date DESC
                LIMIT :limit
            """)
            result = session.execute(query, {"stock_id": stock_id, "limit": n}).fetchall()
            # Convert to date object for easy comparison if it is a datetime
            return {(row[0].date() if isinstance(row[0], datetime) else row[0]): row[1] for row in result}
        except Exception as e:
            print(f"Error fetching last records for stock {stock_id}: {e}")
            return {}
        finally:
            session.close()

    def delete_daily_prices(self, stock_id):
        """
        Deletes all daily prices for a given stock_id.
        Used when a full resync is required (e.g., corporate action).
        """
        session = self.Session()
        try:
            query = text("DELETE FROM daily_prices WHERE stock_id = :stock_id")
            session.execute(query, {"stock_id": stock_id})
            session.commit()
            print(f"Deleted all records for stock_id {stock_id}")
        except Exception as e:
            session.rollback()
            print(f"Error deleting records for stock {stock_id}: {e}")
        finally:
            session.close()

    def get_last_synced_date(self, stock_id):
        """Returns the latest date present in daily_prices for the given stock."""
        session = self.Session()
        try:
            last_date = (
                session.query(DailyPrice.date)
                .filter(DailyPrice.stock_id == stock_id)
                .order_by(DailyPrice.date.desc())
                .first()
            )
            return last_date[0] if last_date else None
        finally:
            session.close()

    def get_all_last_synced_dates(self):
        """Returns a query of stock_id -> max(date) for all stocks."""
        session = self.Session()
        try:
            # Using raw SQL for performance on grouping
            # Or simplified query
            results = session.query(DailyPrice.stock_id, func.max(DailyPrice.date)).group_by(DailyPrice.stock_id).all()

            return {r[0]: r[1] for r in results}
        except Exception as e:
            print(f"Error getting last synced dates: {e}")
            return {}
        finally:
            session.close()

    def insert_daily_prices(self, stock_id, df):
        """Inserts a pandas DataFrame into the database."""
        if df.empty:
            return

        # Prepare DataFrame for insertion
        df_to_insert = df.reset_index().copy()

        # Rename columns to match existing schema
        # Yahoo: Date, Open, High, Low, Close, Volume
        # DB: date, open_price, high_price, low_price, close_price, volume

        df_to_insert = df_to_insert.rename(
            columns={
                "Date": "date",
                "Open": "open_price",
                "High": "high_price",
                "Low": "low_price",
                "Close": "close_price",
                "Volume": "volume",
            }
        )

        df_to_insert["stock_id"] = stock_id
        df_to_insert["created_at"] = datetime.now()

        # Select only relevant columns
        columns = ["stock_id", "date", "open_price", "high_price", "low_price", "close_price", "volume", "created_at"]
        df_to_insert = df_to_insert[columns]

        # Drop rows where close_price is NaN — Prisma cannot handle NaN floats
        df_to_insert = df_to_insert.dropna(subset=["close_price"])
        # Replace remaining NaN values with None (SQL NULL) for other float columns
        df_to_insert = df_to_insert.where(pd.notna(df_to_insert), other=None)

        if df_to_insert.empty:
            print(f"No valid (non-NaN close_price) records to insert for stock_id {stock_id}")
            return

        try:
            df_to_insert.to_sql(
                "daily_prices", self.engine, if_exists="append", index=False, method="multi", chunksize=1000
            )
            print(f"Inserted {len(df_to_insert)} records for stock_id {stock_id}")
        except SQLAlchemyError as e:
            print(f"Error inserting data for stock_id {stock_id}: {e}")

    def insert_batch_daily_prices(self, symbol_map, data_dict):
        """
        Inserts data for multiple stocks efficiently.
        data_dict: {symbol: df}
        symbol_map: {symbol: stock_id}
        """
        dfs_to_insert = []

        for symbol, df in data_dict.items():
            stock_id = symbol_map.get(symbol)
            if not stock_id:
                continue

            df_curr = df.reset_index().copy()
            df_curr = df_curr.rename(
                columns={
                    "Date": "date",
                    "Open": "open_price",
                    "High": "high_price",
                    "Low": "low_price",
                    "Close": "close_price",
                    "Volume": "volume",
                }
            )
            df_curr["stock_id"] = stock_id
            df_curr["created_at"] = datetime.now()

            # Select columns
            cols = ["stock_id", "date", "open_price", "high_price", "low_price", "close_price", "volume", "created_at"]
            # Ensure columns exist
            for c in cols:
                if c not in df_curr.columns:
                    if c == "volume":
                        df_curr[c] = 0
                    else:
                        df_curr[c] = None

            df_curr = df_curr[cols]

            # Drop rows where close_price is NaN — Prisma cannot handle NaN floats
            df_curr = df_curr.dropna(subset=["close_price"])
            # Replace remaining NaN in other float columns with None (SQL NULL)
            df_curr = df_curr.where(pd.notna(df_curr), other=None)

            if not df_curr.empty:
                dfs_to_insert.append(df_curr)

        if not dfs_to_insert:
            return

        final_df = pd.concat(dfs_to_insert, ignore_index=True)

        try:
            final_df.to_sql(
                "daily_prices", self.engine, if_exists="append", index=False, method="multi", chunksize=1000
            )
            print(f"Inserted {len(final_df)} records for {len(data_dict)} stocks.")
        except SQLAlchemyError as e:
            print(f"Error bulk inserting: {e}")

    def bulk_update_market_caps(self, updates):
        """
        Updates market cap for multiple stocks.
        updates: list of dicts {'id': stock_id, 'market_cap': value}
        """
        session = self.Session()
        try:
            session.bulk_update_mappings(Stock, updates)
            session.commit()
            print(f"Updated market caps for {len(updates)} stocks.")
        except Exception as e:
            session.rollback()
            print(f"Error updating market caps: {e}")
        finally:
            session.close()

    def delete_stock_prices(self, stock_id):
        """Deletes all price records for a stock."""
        session = self.Session()
        try:
            session.execute(text("DELETE FROM daily_prices WHERE stock_id = :stock_id"), {"stock_id": stock_id})
            session.commit()
            print(f"Deleted all records for stock_id {stock_id}")
        except Exception as e:
            session.rollback()
            print(f"Error deleting prices for {stock_id}: {e}")
        finally:
            session.close()

    def get_etf_last_synced_date(self, etf_id):
        """Returns the latest date present in etf_daily_prices for the given etf."""
        session = self.Session()
        try:
            last_date = (
                session.query(ETFDailyPrice.date)
                .filter(ETFDailyPrice.etf_id == etf_id)
                .order_by(ETFDailyPrice.date.desc())
                .first()
            )
            return last_date[0] if last_date else None
        finally:
            session.close()

    def get_etf_last_n_records(self, etf_id, n=5):
        """
        Fetches the last n price records for an ETF.
        Returns: dict {date: close_price}
        """
        session = self.Session()
        try:
            query = text("""
                SELECT date, close_price
                FROM etf_daily_prices
                WHERE etf_id = :etf_id
                ORDER BY date DESC
                LIMIT :limit
            """)
            result = session.execute(query, {"etf_id": etf_id, "limit": n}).fetchall()
            return {row[0].date(): row[1] for row in result}
        except Exception as e:
            print(f"Error fetching last records for ETF {etf_id}: {e}")
            return {}
        finally:
            session.close()

    def delete_etf_prices(self, etf_id):
        """Deletes all price records for an ETF."""
        session = self.Session()
        try:
            session.execute(text("DELETE FROM etf_daily_prices WHERE etf_id = :etf_id"), {"etf_id": etf_id})
            session.commit()
            print(f"Deleted all records for etf_id {etf_id}")
        except Exception as e:
            session.rollback()
            print(f"Error deleting prices for ETF {etf_id}: {e}")
        finally:
            session.close()

    def update_performance_metrics(self, stock_id):
        """
        Calculates and updates performance metrics (1w, 1m, 3m, 6m, 1y, 3y, 5y) for a stock.
        """
        session = self.Session()
        try:
            # Get latest date and price
            latest_record = (
                session.query(DailyPrice.date, DailyPrice.close_price)
                .filter(DailyPrice.stock_id == stock_id)
                .order_by(DailyPrice.date.desc())
                .first()
            )

            if not latest_record:
                return

            latest_date, latest_price = latest_record

            # Get latest volume
            latest_volume_record = (
                session.query(DailyPrice.volume)
                .filter(DailyPrice.stock_id == stock_id)
                .order_by(DailyPrice.date.desc())
                .first()
            )
            latest_volume = latest_volume_record[0] if latest_volume_record else None

            # Define time deltas
            # Define time deltas
            deltas = {
                "1w": relativedelta(weeks=1),
                "1m": relativedelta(months=1),
                "3m": relativedelta(months=3),
                "6m": relativedelta(months=6),
                "1y": relativedelta(years=1),
                "3y": relativedelta(years=3),
                "5y": relativedelta(years=5),
            }

            metrics = {}

            for period, delta in deltas.items():
                target_date = latest_date - delta

                # Find nearest record on or before target_date
                past_record = (
                    session.query(DailyPrice.close_price)
                    .filter(DailyPrice.stock_id == stock_id)
                    .filter(DailyPrice.date <= target_date)
                    .order_by(DailyPrice.date.desc())
                    .first()
                )

                if past_record:
                    past_price = past_record[0]
                    if past_price:
                        change = ((latest_price - past_price) / past_price) * 100
                        metrics[f"change_{period}"] = change
                    else:
                        metrics[f"change_{period}"] = None
                else:
                    metrics[f"change_{period}"] = None

            # Upsert into stock_performance
            # Check if record exists
            perf_record = session.query(StockPerformance).filter_by(stock_id=stock_id).first()

            if not perf_record:
                perf_record = StockPerformance(stock_id=stock_id)
                session.add(perf_record)

            perf_record.change_1w = metrics.get("change_1w")
            perf_record.change_1m = metrics.get("change_1m")
            perf_record.change_3m = metrics.get("change_3m")
            perf_record.change_6m = metrics.get("change_6m")
            perf_record.change_1y = metrics.get("change_1y")
            perf_record.change_3y = metrics.get("change_3y")
            perf_record.change_5y = metrics.get("change_5y")
            perf_record.daily_volume = latest_volume
            perf_record.updated_at = datetime.now()

            session.commit()

        except Exception as e:
            session.rollback()
            print(f"Error updating performance for stock {stock_id}: {e}")
        finally:
            session.close()

    # ETF Methods
    def get_etf_symbol_map(self):
        """Returns a dictionary mapping ETF symbol to etf_id."""
        session = self.Session()
        try:
            etfs = session.query(ETF.symbol, ETF.id).all()
            return {e.symbol: e.id for e in etfs if e.symbol}
        except SQLAlchemyError as e:
            print(f"Error fetching ETF symbol map: {e}")
            return {}
        finally:
            session.close()

    def insert_etf(self, symbol, details):
        """
        Inserts a new ETF into the etfs table.
        Returns the etf_id if successful, None otherwise.
        """
        session = self.Session()
        try:
            # Check if it already exists
            existing_etf = session.execute(
                text("SELECT id FROM etfs WHERE symbol = :symbol"), {"symbol": symbol}
            ).fetchone()

            if existing_etf:
                return existing_etf[0]

            query = text("""
                INSERT INTO etfs (symbol, name, underlying_asset, nav, is_active)
                VALUES (:symbol, :name, :underlying_asset, :nav, 1)
                RETURNING id
            """)

            result = session.execute(
                query,
                {
                    "symbol": symbol,
                    "name": details.get("name"),
                    "underlying_asset": details.get("underlying_asset"),
                    "nav": details.get("nav"),
                },
            )
            etf_id = result.fetchone()[0]
            session.commit()
            print(f"Inserted new ETF: {symbol} (ID: {etf_id})")
            return etf_id
        except Exception as e:
            session.rollback()
            print(f"Error inserting ETF {symbol}: {e}")
            return None
        finally:
            session.close()

    def insert_etf_daily_prices(self, etf_id, df):
        """Inserts a pandas DataFrame into the etf_daily_prices table."""
        if df.empty:
            return

        # Prepare DataFrame for insertion
        df_to_insert = df.reset_index().copy()

        df_to_insert = df_to_insert.rename(
            columns={
                "Date": "date",
                "Open": "open_price",
                "High": "high_price",
                "Low": "low_price",
                "Close": "close_price",
                "Volume": "volume",
            }
        )

        df_to_insert["etf_id"] = etf_id
        df_to_insert["created_at"] = datetime.now()

        # Select only relevant columns
        columns = ["etf_id", "date", "open_price", "high_price", "low_price", "close_price", "volume", "created_at"]
        df_to_insert = df_to_insert[columns]

        try:
            df_to_insert.to_sql(
                "etf_daily_prices", self.engine, if_exists="append", index=False, method="multi", chunksize=1000
            )
            print(f"Inserted {len(df_to_insert)} records for etf_id {etf_id}")
        except SQLAlchemyError as e:
            print(f"Error inserting data for etf_id {etf_id}: {e}")

    def update_etf_performance_metrics(self, etf_id):
        """
        Calculates and updates performance metrics (1w, 1m, 3m, 6m, 1y, 3y, 5y) for an ETF.
        """
        session = self.Session()
        try:
            # Get latest date and price
            latest_record = (
                session.query(ETFDailyPrice.date, ETFDailyPrice.close_price)
                .filter(ETFDailyPrice.etf_id == etf_id)
                .order_by(ETFDailyPrice.date.desc())
                .first()
            )

            if not latest_record:
                return

            latest_date, latest_price = latest_record

            # Get latest volume
            latest_volume_record = (
                session.query(ETFDailyPrice.volume)
                .filter(ETFDailyPrice.etf_id == etf_id)
                .order_by(ETFDailyPrice.date.desc())
                .first()
            )
            latest_volume = latest_volume_record[0] if latest_volume_record else None

            # Average daily range % over the last 20 trading days: mean of (high-low)/close*100
            range_rows = (
                session.query(ETFDailyPrice.high_price, ETFDailyPrice.low_price, ETFDailyPrice.close_price)
                .filter(ETFDailyPrice.etf_id == etf_id)
                .order_by(ETFDailyPrice.date.desc())
                .limit(20)
                .all()
            )
            range_pcts = [(h - l) / c * 100 for h, l, c in range_rows if h is not None and l is not None and c]
            avg_range_20d = sum(range_pcts) / len(range_pcts) if range_pcts else None

            # Define time deltas
            deltas = {
                "1w": relativedelta(weeks=1),
                "1m": relativedelta(months=1),
                "3m": relativedelta(months=3),
                "6m": relativedelta(months=6),
                "1y": relativedelta(years=1),
                "3y": relativedelta(years=3),
                "5y": relativedelta(years=5),
            }

            metrics = {}

            for period, delta in deltas.items():
                target_date = latest_date - delta

                # Find nearest record on or before target_date
                past_record = (
                    session.query(ETFDailyPrice.close_price)
                    .filter(ETFDailyPrice.etf_id == etf_id)
                    .filter(ETFDailyPrice.date <= target_date)
                    .order_by(ETFDailyPrice.date.desc())
                    .first()
                )

                if past_record:
                    past_price = past_record[0]
                    if past_price:
                        change = ((latest_price - past_price) / past_price) * 100
                        metrics[f"change_{period}"] = change
                    else:
                        metrics[f"change_{period}"] = None
                else:
                    metrics[f"change_{period}"] = None

            # Upsert into etf_performance
            perf_record = session.query(ETFPerformance).filter_by(etf_id=etf_id).first()

            if not perf_record:
                perf_record = ETFPerformance(etf_id=etf_id)
                session.add(perf_record)

            perf_record.change_1w = metrics.get("change_1w")
            perf_record.change_1m = metrics.get("change_1m")
            perf_record.change_3m = metrics.get("change_3m")
            perf_record.change_6m = metrics.get("change_6m")
            perf_record.change_1y = metrics.get("change_1y")
            perf_record.change_3y = metrics.get("change_3y")
            perf_record.change_5y = metrics.get("change_5y")
            perf_record.daily_volume = latest_volume
            perf_record.avg_range_20d = avg_range_20d
            perf_record.updated_at = datetime.now()

            session.commit()

        except Exception as e:
            session.rollback()
            print(f"Error updating performance for ETF {etf_id}: {e}")
        finally:
            session.close()

    # Index Methods
    def get_index_symbol_map(self):
        """Returns a dictionary mapping Index symbol to index_id."""
        session = self.Session()
        try:
            indices = session.query(Index.symbol, Index.id).all()
            return {i.symbol: i.id for i in indices if i.symbol}
        except SQLAlchemyError as e:
            print(f"Error fetching Index symbol map: {e}")
            return {}
        finally:
            session.close()

    def insert_index(self, symbol, details):
        """
        Inserts a new Index into the indices table.
        Returns the index_id if successful, None otherwise.
        """
        session = self.Session()
        try:
            # Check if it already exists
            existing_index = session.execute(
                text("SELECT id FROM indices WHERE symbol = :symbol"), {"symbol": symbol}
            ).fetchone()

            if existing_index:
                return existing_index[0]

            query = text("""
                INSERT INTO indices (symbol, name, is_active)
                VALUES (:symbol, :name, 1)
                RETURNING id
            """)

            result = session.execute(query, {"symbol": symbol, "name": details.get("name")})
            index_id = result.fetchone()[0]
            session.commit()
            print(f"Inserted new Index: {symbol} (ID: {index_id})")
            return index_id
        except Exception as e:
            session.rollback()
            print(f"Error inserting Index {symbol}: {e}")
            return None
        finally:
            session.close()

    def get_index_last_synced_date(self, index_id):
        """Returns the latest date present in index_daily_prices for the given index."""
        session = self.Session()
        try:
            last_date = (
                session.query(IndexDailyPrice.date)
                .filter(IndexDailyPrice.index_id == index_id)
                .order_by(IndexDailyPrice.date.desc())
                .first()
            )
            return last_date[0] if last_date else None
        finally:
            session.close()

    def get_index_last_n_records(self, index_id, n=5):
        """
        Fetches the last n price records for an Index.
        Returns: dict {date: close_price}
        """
        session = self.Session()
        try:
            query = text("""
                SELECT date, close_price
                FROM index_daily_prices
                WHERE index_id = :index_id
                ORDER BY date DESC
                LIMIT :limit
            """)
            result = session.execute(query, {"index_id": index_id, "limit": n}).fetchall()
            return {row[0].date(): row[1] for row in result}
        except Exception as e:
            print(f"Error fetching last records for Index {index_id}: {e}")
            return {}
        finally:
            session.close()

    def delete_index_prices(self, index_id):
        """Deletes all price records for an Index."""
        session = self.Session()
        try:
            session.execute(text("DELETE FROM index_daily_prices WHERE index_id = :index_id"), {"index_id": index_id})
            session.commit()
            print(f"Deleted all records for index_id {index_id}")
        except Exception as e:
            session.rollback()
            print(f"Error deleting prices for Index {index_id}: {e}")
        finally:
            session.close()

    def insert_index_daily_prices(self, index_id, df):
        """Inserts a pandas DataFrame into the index_daily_prices table."""
        if df.empty:
            return

        # Prepare DataFrame for insertion
        df_to_insert = df.reset_index().copy()

        df_to_insert = df_to_insert.rename(
            columns={
                "Date": "date",
                "Open": "open_price",
                "High": "high_price",
                "Low": "low_price",
                "Close": "close_price",
                "Volume": "volume",
            }
        )

        df_to_insert["index_id"] = index_id
        df_to_insert["created_at"] = datetime.now()

        # Select only relevant columns
        columns = ["index_id", "date", "open_price", "high_price", "low_price", "close_price", "volume", "created_at"]
        df_to_insert = df_to_insert[columns]

        try:
            df_to_insert.to_sql(
                "index_daily_prices", self.engine, if_exists="append", index=False, method="multi", chunksize=1000
            )
            print(f"Inserted {len(df_to_insert)} records for index_id {index_id}")
        except SQLAlchemyError as e:
            print(f"Error inserting data for index_id {index_id}: {e}")

    def update_index_performance_metrics(self, index_id):
        """
        Calculates and updates performance metrics (1w, 1m, 3m, 6m, 1y, 3y, 5y) for an Index.
        """
        session = self.Session()
        try:
            # Get latest date and price
            latest_record = (
                session.query(IndexDailyPrice.date, IndexDailyPrice.close_price)
                .filter(IndexDailyPrice.index_id == index_id)
                .order_by(IndexDailyPrice.date.desc())
                .first()
            )

            if not latest_record:
                return

            latest_date, latest_price = latest_record

            # Get latest volume
            latest_volume_record = (
                session.query(IndexDailyPrice.volume)
                .filter(IndexDailyPrice.index_id == index_id)
                .order_by(IndexDailyPrice.date.desc())
                .first()
            )
            latest_volume = latest_volume_record[0] if latest_volume_record else None

            # Define time deltas
            deltas = {
                "1w": relativedelta(weeks=1),
                "1m": relativedelta(months=1),
                "3m": relativedelta(months=3),
                "6m": relativedelta(months=6),
                "1y": relativedelta(years=1),
                "3y": relativedelta(years=3),
                "5y": relativedelta(years=5),
            }

            metrics = {}

            for period, delta in deltas.items():
                target_date = latest_date - delta

                # Find nearest record on or before target_date
                past_record = (
                    session.query(IndexDailyPrice.close_price)
                    .filter(IndexDailyPrice.index_id == index_id)
                    .filter(IndexDailyPrice.date <= target_date)
                    .order_by(IndexDailyPrice.date.desc())
                    .first()
                )

                if past_record:
                    past_price = past_record[0]
                    if past_price:
                        change = ((latest_price - past_price) / past_price) * 100
                        metrics[f"change_{period}"] = change
                    else:
                        metrics[f"change_{period}"] = None
                else:
                    metrics[f"change_{period}"] = None

            # Upsert into index_performance
            perf_record = session.query(IndexPerformance).filter_by(index_id=index_id).first()

            if not perf_record:
                perf_record = IndexPerformance(index_id=index_id)
                session.add(perf_record)

            perf_record.change_1w = metrics.get("change_1w")
            perf_record.change_1m = metrics.get("change_1m")
            perf_record.change_3m = metrics.get("change_3m")
            perf_record.change_6m = metrics.get("change_6m")
            perf_record.change_1y = metrics.get("change_1y")
            perf_record.change_3y = metrics.get("change_3y")
            perf_record.change_5y = metrics.get("change_5y")
            perf_record.daily_volume = latest_volume
            perf_record.updated_at = datetime.now()

            session.commit()

        except Exception as e:
            session.rollback()
            print(f"Error updating performance for Index {index_id}: {e}")
        finally:
            session.close()


class StockPerformance(Base):
    __tablename__ = "stock_performance"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, nullable=False, unique=True)
    change_1w = Column(Float)
    change_1m = Column(Float)
    change_3m = Column(Float)
    change_6m = Column(Float)
    change_1y = Column(Float)
    change_3y = Column(Float)
    change_5y = Column(Float)

    # Momentum Metrics
    volatility = Column(Float)

    # Momentum Ratios
    mr_1m = Column(Float)
    mr_3m = Column(Float)
    mr_6m = Column(Float)
    mr_1y = Column(Float)

    # Z-Scores
    z_1m = Column(Float)
    z_3m = Column(Float)
    z_6m = Column(Float)
    z_1y = Column(Float)

    momentum_score = Column(Float)
    simple_momentum_score = Column(Float)

    daily_volume = Column(BigInteger)
    updated_at = Column(DateTime, default=datetime.now)

    # VCP Metrics
    is_vcp = Column(Boolean, default=False)
    vcp_score = Column(Float)

    # Stage 2 (Minervini Trend Template) Metrics
    is_stage2 = Column(Boolean, default=False)
    stage2_rs_rank = Column(Float)
    stage2_pct_from_52w_high = Column(Float)
    stage2_pct_above_52w_low = Column(Float)

    # Average Daily Range % (20-day mean of high/low - 1)
    adr_pct = Column(Float)

    # Swing Score: equal-weighted composite of 4 components (each 0-100)
    strong_stock_score = Column(Float)  # Stage 2 trend template: criteria passed / 7
    sector_score = Column(Float)  # percentile rank of mapped sector's 1M return
    adr_score = Column(Float)  # percentile rank of adr_pct across universe
    swing_score = Column(Float)  # avg(strong_stock_score, stage2_rs_rank, sector_score, adr_score)


class MomentumHistory(Base):
    __tablename__ = "momentum_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    momentum_score = Column(Float)
    rank = Column(Integer)

    __table_args__ = (Index("idx_momentum_history_stock_date", "stock_id", "date", unique=True),)


# ETF Models
class ETF(Base):
    __tablename__ = "etfs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), unique=True, nullable=False)
    name = Column(String(255))
    underlying_asset = Column(String(255))
    nav = Column(Float)
    is_active = Column(Integer, default=True)
    security_id = Column(Integer)
    isin = Column(String(20))
    series = Column(String(10))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime)


class ETFDailyPrice(Base):
    __tablename__ = "etf_daily_prices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    etf_id = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(BigInteger)
    created_at = Column(DateTime, default=datetime.now)


class ETFPerformance(Base):
    __tablename__ = "etf_performance"
    id = Column(Integer, primary_key=True, autoincrement=True)
    etf_id = Column(Integer, nullable=False, unique=True)
    change_1w = Column(Float)
    change_1m = Column(Float)
    change_3m = Column(Float)
    change_6m = Column(Float)
    change_1y = Column(Float)
    change_3y = Column(Float)
    change_5y = Column(Float)
    daily_volume = Column(BigInteger)
    avg_range_20d = Column(Float)
    updated_at = Column(DateTime, default=datetime.now)


# SME (NSE Small and Medium Enterprise board) Models - deliberately
# separate from Stock/DailyPrice, do not mix universes.
class SME(Base):
    __tablename__ = "sme_stocks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), unique=True, nullable=False)
    name = Column(String(255))
    isin = Column(String(20))
    security_id = Column(Integer)  # Dhan's security_id, for re-sync lookups
    series = Column(String(5))  # SM / ST / SZ
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime)


class SMEDailyPrice(Base):
    __tablename__ = "sme_daily_prices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sme_stock_id = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(BigInteger)
    created_at = Column(DateTime, default=datetime.now)


class SMEPerformance(Base):
    __tablename__ = "sme_performance"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sme_stock_id = Column(Integer, nullable=False, unique=True)
    change_1w = Column(Float)
    change_1m = Column(Float)
    change_3m = Column(Float)
    change_6m = Column(Float)
    change_1y = Column(Float)
    change_3y = Column(Float)
    change_5y = Column(Float)
    daily_volume = Column(BigInteger)
    updated_at = Column(DateTime, default=datetime.now)


# Index Models
class Index(Base):
    __tablename__ = "indices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), unique=True, nullable=False)
    name = Column(String(255))
    is_active = Column(Integer, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime)


class IndexDailyPrice(Base):
    __tablename__ = "index_daily_prices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    index_id = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(BigInteger)
    created_at = Column(DateTime, default=datetime.now)


class IndexPerformance(Base):
    __tablename__ = "index_performance"
    id = Column(Integer, primary_key=True, autoincrement=True)
    index_id = Column(Integer, nullable=False, unique=True)
    change_1w = Column(Float)
    change_1m = Column(Float)
    change_3m = Column(Float)
    change_6m = Column(Float)
    change_1y = Column(Float)
    change_3y = Column(Float)
    change_5y = Column(Float)
    daily_volume = Column(BigInteger)
    updated_at = Column(DateTime, default=datetime.now)
