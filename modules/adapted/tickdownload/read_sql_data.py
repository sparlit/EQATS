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


# pylint: disable-msg=broad-except, global-statement

import pandas as pd
from sqlalchemy import desc
from tickerplot.sql.sqlalchemy_wrapper import (
    create_or_get_all_scrips_table,
    create_or_get_nse_equities_hist_data,
    execute_one,
    get_metadata,
    select_expr,
)

_DB_METADATA = None


def get_all_scrips_names_in_db(metadata=None):
    all_scrips_table = create_or_get_all_scrips_table(metadata=metadata)
    scrips_select_st = select_expr([all_scrips_table.c.nse_symbol]).where(all_scrips_table.c.nse_traded)

    result = execute_one(scrips_select_st, engine=metadata.bind)
    return [row[0] for row in result.fetchall()]


# FIXME metadata=None doesn't look correct, we need to pass db_meta perhaps?
def get_hist_data_as_dataframes_dict(metadata=None, limit=0, max_scrips=16000):
    lscrips = get_all_scrips_names_in_db(metadata=metadata)

    e = metadata.bind
    hist_data = create_or_get_nse_equities_hist_data(metadata=metadata)

    scripdata_dict = {}
    scrips = 0
    for scrip in lscrips:
        sql_st = (
            select_expr(
                [
                    hist_data.c.date,
                    hist_data.c.open,
                    hist_data.c.high,
                    hist_data.c.low,
                    hist_data.c.close,
                    hist_data.c.volume,
                    hist_data.c.delivery,
                ]
            )
            .where(hist_data.c.symbol == scrip)
            .order_by(desc(hist_data.c.date))
        )

        if limit and isinstance(limit, int) and limit > 0:
            sql_st = sql_st.limit(limit)

        scripdata = pd.io.sql.read_sql(sql_st, e)

        scripdata.columns = ["date", "open", "high", "low", "close", "volume", "delivery"]
        scripdata = scripdata.reset_index()
        scripdata = scripdata.set_index(pd.DatetimeIndex(scripdata["date"]))
        scripdata = scripdata.drop("date", axis=1)
        scripdata_dict[scrip] = scripdata

        scrips += 1
        if scrips == max_scrips:
            break

    return scripdata_dict


def main(args):

    import argparse

    parser = argparse.ArgumentParser()

    # --dbpath option
    parser.add_argument("--dbpath", help="Database URL to be used.", dest="dbpath")

    args = parser.parse_args()

    # Make sure we can access the DB path if specified or else exit right here.
    if args.dbpath:
        try:
            global _DB_METADATA
            _DB_METADATA = get_metadata(args.dbpath)
        except Exception as e:
            print(f"Not a valid DB URL: {args.dbpath} (Exception: {e})")
            return -1

    get_hist_data_as_dataframes_dict()

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv))
