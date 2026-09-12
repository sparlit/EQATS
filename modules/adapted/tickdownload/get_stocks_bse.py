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


#
# Refer to LICENSE file and README file for licensing information.
#
# A simple script that tries to download the historical stock data
# for a BSE scrip

import os
from datetime import datetime as dt

import bs4
import requests
from tickerplot.utils.logger import get_logger

module_logger = get_logger(os.path.basename(__file__))

GLOBAL_START_DATE = "01/01/2002"
DATE_FORMAT = "%d/%m/%Y"
DATE_FMT_FNAME = "%Y%m%d"


def get_data_for_security(script_code, sdate, edate=None):
    sdate = dt.strptime(sdate, "%d/%m/%Y")
    edate = dt.strptime(edate, "%d/%m/%Y") if edate is not None else dt.today()
    _do_get_data_for_security(script_code, sdate, edate)


def _do_get_data_for_security(script_code, sdate, edate):
    sdate = dt.strftime(sdate, DATE_FORMAT)
    edate = dt.strftime(edate, DATE_FORMAT)
    url = "http://www.bseindia.com/markets/equity/EQReports/StockPrcHistori.aspx?expandable=7&flag=0"

    module_logger.info("GET: %s", url)
    x = requests.get(url)

    html = bs4.BeautifulSoup(x.text, "html.parser")

    hidden_elems = html.findAll(attrs={"type": "hidden"})

    form_data = {}
    for el in hidden_elems:
        m = el.attrs
        if "value" in m:
            form_data[m["name"]] = m["value"]

    other_data = {
        "WINDOW_NAMER": "1",
        "myDestination": "#",
        "ctl00$ContentPlaceHolder1$txtFromDate": sdate,
        "ctl00$ContentPlaceHolder1$txtToDate": edate,
        "ctl00$ContentPlaceHolder1$search": "rad_no1",
        "ctl00$ContentPlaceHolder1$hidYear": "",
        "ctl00$ContentPlaceHolder1$hidToDate": edate,
        "ctl00$ContentPlaceHolder1$hidOldDMY": "",
        "ctl00$ContentPlaceHolder1$hidFromDate": sdate,
        "ctl00$ContentPlaceHolder1$hidDMY": "D",
        "ctl00$ContentPlaceHolder1$hiddenScripCode": script_code,
        "ctl00$ContentPlaceHolder1$Hidden2": "",
        "ctl00$ContentPlaceHolder1$Hidden1": "",
        "ctl00$ContentPlaceHolder1$hidCurrentDate": edate,
        "ctl00$ContentPlaceHolder1$hidCompanyVal": "SUBEX",
        "ctl00$ContentPlaceHolder1$hdnCode": script_code,
        "ctl00$ContentPlaceHolder1$hdflag": "0",
        "ctl00$ContentPlaceHolder1$GetQuote1_smartSearch2": "Enter Script Name",
        "ctl00$ContentPlaceHolder1$GetQuote1_smartSearch": "SUBEX LTD",
        "ctl00$ContentPlaceHolder1$DMY": "rdbDaily",
        "ctl00$ContentPlaceHolder1$DDate": "",
    }

    dl2_map = {
        "ctl00$ContentPlaceHolder1$btnDownload.x": "9",
        "ctl00$ContentPlaceHolder1$btnDownload.y": "5",
    }

    form_data.update(other_data)
    form_data.update(dl2_map)

    module_logger.info("POST: %s", url)
    module_logger.debug("POST Data: %s", form_data)
    y = requests.post(url, data=form_data, stream=True)

    if y.ok:
        start_end = "_".join([sdate.replace("/", ""), edate.replace("/", ""), ""])
        fname = start_end + script_code + ".csv"
        with open(fname, "wb") as handle:
            for block in y.iter_content(1024):
                if not block:
                    break
                handle.write(block)
    else:
        module_logger.error("Error(POST): %s", y.text)


if __name__ == "__main__":
    print(get_data_for_security("500002", GLOBAL_START_DATE))
    # for x in bse_get_all_stocks_list(100,1):
    # get_data_for_security(x.bseid, GLOBAL_START_DATE)
