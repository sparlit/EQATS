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
Created on Nov 23, 2015

@author: ashish
"""
import csv
import datetime
import time

import imp

# imp.load_source("config","/cygdrive/c/Users/ashish/Desktop/workspace/NSEDataAnalytics/neoPath/config.py")
import MySQLdb
from dateutil.parser import parse

import config
from config import tests, type


def insert_into_database(File, database, single_or_many):
    db = MySQLdb.connect(config.host, config.user, config.password, config.database)
    cursor = db.cursor()
    try:
        csv_data = csv.reader(file(File))

        format = ",".join(["%s" for m in range(len(csv_data.next()))])
        if single_or_many:
            for row in csv_data:
                data = [
                    int(m)
                    if type(m) == int
                    else float(m)
                    if type(m) == float
                    else parse(m).strftime("%Y-%m-%d %H:%M:%S")
                    if type(m) == datetime
                    else m
                    for m in row
                ]

                try:
                    cursor.execute(f"insert into {database} values({format})", data)
                    db.commit()
                except MySQLdb.Error:
                    raise
        else:
            data = list(csv_data)

            try:
                format = ",".join(["%s" for m in range(len(data[0]))])

                cursor.executemany(f"insert into {database} values({format})", data)
                db.commit()
            except MySQLdb.Error:
                raise

    except OSError:
        raise
    finally:
        db.close()


if __name__ == "__main__":
    File = r"C:\Users\ashish\Downloads\NeoFeedPlus (1)\data_20151123_v1.csv"
    database = "test"
    insert_into_database(File, database, 1)
