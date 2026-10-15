import datetime
import os
import random
import re
import time
from collections import namedtuple
from datetime import date as dt_date
from datetime import datetime as dt

import pandas as pd
import pytz
import requests
from tickerplot.nse.nse_utils import nse_get_all_stocks_list
from tickerplot.sql.sqlalchemy_wrapper import (
    create_or_get_nse_corp_actions_hist_data,
    execute_many_insert,
    get_metadata,
)
from tickerplot.utils.logger import get_logger


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


#
# Refer to LICENSE file and README file for licensing information.
#
# pylint: disable-msg=broad-except,global-statement

"""Get's data for corporate Actions for a given stock on NSE. Parses and
stores the bonus and face value splits and dividends.

For NSE we have data reliably from 1st Jan 2005. For older data, we might
have to refer to BSE data.

For every corp action, we output data in the following form -
scrip, ex_date, type(B:bonus,D:dividend,S:split), ratio, value.
ratio < 1.0 for bonus/split, value in Rs. for div"""

module_logger = get_logger(os.path.basename(__file__))

# _CorpActionAll is a named tuple of following type
# "Symbol","Company","Industry","Series","Face Value(Rs.)","Purpose",
# "Ex-Date","Record Date","BC Start Date","BC End Date",
# "No Delivery Start Date","No Delivery End Date"
_CorpActionAll = namedtuple(
    "_CorpActionAll",
    [
        "sym",
        "name",
        "industry",
        "series",
        "fv",
        "purpose",
        "ex_date",
        "rec_date",
        "bc_sdate",
        "bc_edate",
        "nd_sdate",
        "nd_edate",
    ],
)

CorpAction = namedtuple("CorpAction", ["sym", "ex_date", "action", "ratio", "delta"])


# Don't ask me how I got these regex, lots of trial/error
_div_regex = re.compile(r"(?:.*?)(?P<div>(?:(?:div.*?)(\d+%)|(?:div.*?(rs\.?)?)\s*(\d+\.?\d*)))")
_rsr_regex = re.compile(r"rs\.?")
_num_per_r = re.compile(r"(\d+\.?\d{0,2}%?)")
_bonus_regex = re.compile(r"bon.*?(\d+)\s*:\s*(\d)")
_split_regex = re.compile(r".*f(?:.*?)v.*.*?spl.*?(\d+).*?(\d+).*")


def _do_process_purpose(action):
    """Does all the 'hard work' in processing the purpose. Returns a single
    line of the form
    symbol, ex_date(yyyy-mm-dd), purpose(d/b/s), ratio(for b/s), value(for d),
    """
    symbol = action.sym.upper()
    purpose = action.purpose.lower()
    ex_date = action.ex_date
    fv = float(action.fv)
    actions = []
    if purpose.find("div") >= 0:
        # r = re.compile(r'(?:.*?)(?P<Div>(?:div.*?)?((?:(rs.*?)|(\s+))\d+\.?\d*((?:\/-)|%)?))')
        # r = re.compile(r'(?:.*?)(?P<Div>(?:div.*?)((?:(rs\.*?)|(\s+))\d+\.?\d*(?:\/-)?)|(\d+%))')

        # r = re.compile(r'(?:.*?)(?P<div>(?:(?:div.*?)(\\d+%)|(?:div.*?(rs\\.?)?)\\s*(\\d+\\.?\\d*)))')

        for x in _div_regex.finditer(purpose):
            for _, v in x.groupdict().items():
                v = re.sub(_rsr_regex, "", v)
                for y in _num_per_r.finditer(v):
                    z = y.group()
                    div = float(z.replace("%", "")) * (fv / 100) if z.find("%") > 0 else float(z)
                actions.append(CorpAction(symbol, ex_date, "D", 1.0, div))
    if purpose.find("bon") >= 0:
        y = _bonus_regex.search(purpose)
        if y:
            n, d = float(y.group(1)), float(y.group(2))
            ratio = n / (n + d)
            action = CorpAction(symbol, ex_date, "B", ratio, 0.0)
            actions.append(action)
            module_logger.debug("CorpAction: %s", str(CorpAction))
    if purpose.find("spl") >= 0:
        y = _split_regex.search(purpose)
        if y:
            d, n = float(y.group(1)), float(y.group(2))
            ratio = n / d
            action = CorpAction(symbol, ex_date, "S", ratio, 0.0)
            actions.append(action)
            module_logger.debug("CorpAction: %s", str(CorpAction))
    return actions


def process_corp_actions_from_date(corp_actions, start_date=None, action_types=None):
    """Filters corporate actions on or after start_date, optionally filtering by action_types (e.g. ['B', 'S']).

    Args:
        corp_actions (list[CorpAction]): List of CorpAction tuples.
        start_date (datetime.date | str | None): Cutoff start date.
        action_types (iterable[str] | None): Filter by action codes (e.g. ['B', 'S', 'D']).

    Returns:
        list[CorpAction]: Filtered list of corporate actions sorted by ex_date.
    """
    if start_date is None and action_types is None:
        return list(corp_actions)

    cutoff = None
    if start_date is not None:
        if isinstance(start_date, dt_date) and not isinstance(start_date, dt):
            cutoff = start_date
        elif isinstance(start_date, dt):
            cutoff = start_date.date()
        elif isinstance(start_date, str):
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
                try:
                    cutoff = dt.strptime(start_date, fmt).date()
                    break
                except ValueError:
                    pass
            if cutoff is None:
                raise ValueError(f"Invalid start_date format: {start_date}")

    filtered = []
    allowed_types = set(action_types) if action_types is not None else None

    for act in corp_actions:
        act_date = getattr(act, "ex_date", None)
        if isinstance(act_date, dt):
            act_date = act_date.date()
        elif isinstance(act_date, str):
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
                try:
                    act_date = dt.strptime(act_date, fmt).date()
                    break
                except ValueError:
                    pass

        if cutoff is not None and isinstance(act_date, dt_date) and act_date < cutoff:
            continue
        if allowed_types is not None and getattr(act, "action", None) not in allowed_types:
            continue
        filtered.append(act)

    return filtered


def adjust_prices_for_bonus_split(df: pd.DataFrame, corp_actions, start_date=None) -> pd.DataFrame:
    """Adjusts OHLCV prices and volumes in DataFrame for bonus ('B') and split ('S') corporate actions
    occurring on or after start_date.

    Args:
        df (pandas.DataFrame): Historical price data indexed by Timestamp/Date.
        corp_actions (list[CorpAction]): List of CorpAction tuples.
        start_date (datetime.date | str | None): Optional date filter for actions.

    Returns:
        pandas.DataFrame: Adjusted DataFrame.
    """
    if df.empty or not corp_actions:
        return df

    df_adjusted = df.copy()
    actions_to_apply = process_corp_actions_from_date(corp_actions, start_date=start_date, action_types=["B", "S"])

    for act in actions_to_apply:
        ex_dt = act.ex_date
        if not isinstance(ex_dt, pd.Timestamp):
            ex_dt = pd.Timestamp(ex_dt)
        ratio = float(act.ratio)
        if ratio <= 0:
            continue

        mask = df_adjusted.index < ex_dt
        for col in df_adjusted.columns:
            col_lower = str(col).lower()
            if col_lower in ["o", "open", "h", "high", "l", "low", "c", "close"]:
                df_adjusted.loc[mask, col] = df_adjusted.loc[mask, col] * ratio
            elif col_lower in ["v", "volume", "d", "deliverable"]:
                df_adjusted.loc[mask, col] = df_adjusted.loc[mask, col] / ratio

    return df_adjusted


def _process_purpose(corp_actions, start_date=None, action_types=None):
    """Takes a list of `corp_actions` named tuples and processes the text of the purpose,
    generating a list of CorpAction namedtuples. Option to filter from a start_date or action_types.
    """
    actions = []
    for a in corp_actions:
        actions.extend(_do_process_purpose(a))
    return process_corp_actions_from_date(actions, start_date=start_date, action_types=action_types)


def _process_ca_text(ca_text, start_date=None, action_types=None):
    """Processes a CA text and returns a list of CorpAction tuples.
    Supports filtering by start_date and action_types.
    """
    corp_actions = []
    for line in ca_text.split("\n"):
        line_parts = [x.strip().replace('"', "") for x in line.split(",")]
        if line_parts[0].lower() == "symbol":
            continue
        if len(line_parts) < len(_CorpActionAll._fields):
            module_logger.info("Not Processed: %s", line_parts)
            continue
        line_parts[6] = dt.date(dt.strptime(line_parts[6], "%d-%b-%Y"))
        a = _CorpActionAll(*line_parts)
        corp_actions.append(a)
    return _process_purpose(
        sorted(set(corp_actions), key=lambda x: x.ex_date),
        start_date=start_date,
        action_types=action_types,
    )


def get_corp_action_csv(sym_name=None, time_period=None, start_date=None, action_types=None):
    """Gets the corp action CSV for the symbol name or time_period, with optional
    filtering by start_date and action_types (e.g. ['B', 'S']).
    """
    ca_text = ""
    if sym_name:
        sym_name = sym_name.upper().replace("&", "%26")
        base = "http://nseindia.com/corporates/datafiles/"
        sym_part = f"CA_{sym_name}_LAST_24_MONTHS.csv"
        url = base + sym_part
        module_logger.info("GET: %s", url)
        r = requests.get(url)
        if r.ok:
            ca_text += r.text
        else:
            module_logger.error("GET: %s(%d)", url, r.status_code)

        sym_part2 = f"CA_{sym_name}_MORE_THAN_24_MONTHS.csv"
        url = base + sym_part2
        module_logger.info("GET: %s", url)
        r = requests.get(url)
        if r.ok:
            ca_text += r.text
        else:
            module_logger.error("GET: %s(%d)", url, r.status_code)

    if time_period:
        base = "http://nseindia.com/corporates/datafiles/"
        sym_part = f"CA_LAST_{time_period}.csv"
        url = base + sym_part
        module_logger.info("GET: %s", url)
        r = requests.get(url)
        if r.ok:
            ca_text += r.text
        else:
            module_logger.error("GET: %s(%d)", url, r.status_code)

    return _process_ca_text(ca_text, start_date=start_date, action_types=action_types)


def main(args):

    import argparse

    parser = argparse.ArgumentParser()

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--all",
        help="Download data for all stocks. Usually you'd have to do it only once.",
        dest="all_stocks",
        action="store_true",
    )

    group.add_argument(
        "--from", help="Download data from this data. Date Format 'DD-MM-YYYY'.", dest="from_date"
    )

    # --dbpath option
    parser.add_argument("--dbpath", help="Database URL to be used.", dest="dbpath")

    args, unprocessed = parser.parse_known_args()

    # Make sure we can access the DB path if specified or else exit right here.
    if args.dbpath:
        try:
            db_meta = get_metadata(args.dbpath)
        except Exception as e:
            print(f"Not a valid DB URL: {args.dbpath} (Exception: {e})")
            return -1

    all_corp_actions = []
    if args.all_stocks:
        unprocessed = (x.symbol for x in nse_get_all_stocks_list())

    # It's possible to give --from DD-MM-YYYY infy (say), just help
    for stock in unprocessed:
        time.sleep(random.randint(1, 5))
        try:
            corp_actions = get_corp_action_csv(sym_name=stock)
        except Exception as e:
            module_logger.exception(e)
            continue
        all_corp_actions.extend(corp_actions)

    if args.from_date:
        try:
            from_date = dt.date(dt.strptime(args.from_date, "%d-%m-%Y"))
            today = dt.date(dt.now())
            td = today - from_date
            if td.days < 0:
                print("From date cannot be greater than today.")
                return -1
            if td.days < 15:
                corp_actions = get_corp_action_csv(time_period="15_DAYS")
            else:
                corp_actions = get_corp_action_csv(time_period="3_MONTHS")

            all_corp_actions.extend(corp_actions)

        except ValueError:
            print(f"Date '{args.from_date}' in unsupported format")
            return -1

    tbl = create_or_get_nse_corp_actions_hist_data(metadata=db_meta)

    all_insert_statements = []
    for corp_action in all_corp_actions:
        module_logger.debug("CorpAction :%s", str(corp_action))
        insert_st = tbl.insert().values(
            symbol=corp_action.sym,
            ex_date=corp_action.ex_date,
            action=corp_action.action,
            ratio=corp_action.ratio,
            delta=corp_action.delta,
        )
        all_insert_statements.append(insert_st)
        module_logger.debug("insert_st : %s", insert_st.compile().params)

    results = execute_many_insert(all_insert_statements, engine=db_meta.bind)
    for result in results:
        result.close()

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
