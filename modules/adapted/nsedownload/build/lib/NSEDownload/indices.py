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


import datetime

from NSEDownload.check import check_name
from NSEDownload.scraper import scrape_data
from NSEDownload.static_data import (
    arr,
    arrTRI,
    get_historical_index_url,
    get_tri_index_url,
    values,
    valuesTRI,
)


def get_data(
    indexName, full_data=False, start_date=None, end_date=None, indextype=None, check_index=True
):
    """
    To get data for indices using dates or full_data

    Args:
        indexName (str): Name of index to scrape
        full_data (bool, optional): If set to True, then complete data is scrape. Defaults to False.
        start_date (str, optional): start date of date range in YYYY-MM-DD or DD-MM-YYYY format. Defaults to None.
        end_date (str, optional): end date of date range in YYYY-MM-DD or DD-MM-YYYY format. Defaults to None.
        indextype (str, optional): 'historical' or 'TRI'. Defaults to None.
        check_index (bool, optional): If set to true, the index is checked with internal list of indices and returns closest name if not present in list. Defaults to True.

    Raises:
        ValueError: If no dates are provided/ Incorrect format of dates/ If start date > end date

    Returns:
        DataFrame: DataFrame containing data for index for given date range

    ##Example:
    ```
    from NSEDownload import indices
    # Getting historical data for index using date range
    df = indices.get_data(indexName = "NIFTY Shariah 25",start_date="09-01-2017",end_date="14-08-2019")
    ```

    Output
    ```
            Open High Low    Close    Shares Traded Turnover (Rs. Cr)
    Date
    2017-01-09    -    -   -  3281.54                -                 -
    2017-01-10    -    -   -  3295.08                -                 -
    2017-01-11    -    -   -  3327.22                -                 -
    2017-01-12    -    -   -  3323.66                -                 -
    2017-01-13    -    -   -  3306.55                -                 -
    ...         ...  ...  ..      ...              ...               ... ..
    2018-01-02    -    -   -  4279.85         48401645           2403.21
    2018-01-03    -    -   -  4277.67         46232696           3194.03
    2018-01-04    -    -   -  4323.68         50699017           3333.30
    2018-01-05    -    -   -  4354.23         56414034           3668.95
    2018-01-08    -    -   -  4382.23         42746996           2925.44

    [249 rows start_date 7 columns]
    ```

    ```
    from NSEDownload import indices
    # Using full_data argument to get complete data since inception
    df = indices.get_data(indexName = "NIFTY 100", full_data=True)

    # Getting TRI data
    df = indices.get_data(indexName = "NIFTY 100", full_data=True, indextype="TRI")

    ```

    """

    url, Array, Values = get_historical_index_url(), arr, values

    if indextype == "TRI" or indextype == "tri" or indextype == "T" or indextype == "t":
        url, Array, Values = get_tri_index_url(), arrTRI, valuesTRI

    if check_index is True:
        check_name(Array, Values, indexName)

    if full_data is False:
        if start_date is None or end_date is None:
            raise ValueError("Provide start and end date. ")

        x = parse_date(start_date)
        y = parse_date(end_date)

        if x > y:
            raise ValueError("Starting date is greater than end date.")

    else:
        print("Downloading Full data for", indexName)
        x = datetime.datetime.strptime("1-1-1990", "%d-%m-%Y")
        y = datetime.datetime.today()

    result = scrape_data(x, y, "index", indexName=indexName, url=url)
    return result


def parse_date(text):
    """
    Parses date in either YYYY-MM-DD or DD-MM-YYYY format
    """

    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            pass

    raise ValueError("Dates should be in YYYY-MM-DD or DD-MM-YYYY format")
