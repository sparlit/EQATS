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
""" Downloads Corp Actions for a given security, We are mainly interested in
bonus and splits, but doesn't harm to keep noting others.

BSE corp actions data is one of the worsts you'd find, we are just going to
try harder as much as we can. eg.
 - For a number of splits there's no pre and post split value
 - For a number of corporate actions there is no ex_date. We use heuristics
   there to get previous business day before record date if it's there.
"""

import sys

import bs4
import requests

url = "http://www.bseindia.com/corporates/corporate_act.aspx"

r = requests.get(url)

html = bs4.BeautifulSoup(r.text, "html.parser")
hidden_elems = html.findAll(attrs={"type": "hidden"})
form_data = {}
for el in hidden_elems:
    m = el.attrs
    if "value" in m:
        form_data[m["name"]] = m["value"]
    else:
        form_data[m["name"]] = ""

other_data = {
    "__EVENTTARGET": "",
    "__EVENTARGUMENT": "",
    "myDestination": "#",
    "WINDOW_NAMER": "1",
    "ctl00$ContentPlaceHolder1$hdnCode": "590082",
    "ctl00$ContentPlaceHolder1$hndvalue": "D",
    "ctl00$ContentPlaceHolder1$hnd": "",
    "ctl00$ContentPlaceHolder1$hdnCheck": "",
    "ctl00$ContentPlaceHolder1$date": "exdate",
    "ctl00$ContentPlaceHolder1$txtDate": "",
    "ctl00$ContentPlaceHolder1$txtTodate": "",
    "ctl00$ContentPlaceHolder1$Hidden1": "",
    "ctl00$ContentPlaceHolder1$GetQuote1_smartSearch": "ABB India Limited",
    "ctl00$ContentPlaceHolder1$ddlPurpose": "Select",
}

button_data = {"ctl00$ContentPlaceHolder1$btnSubmit.x": "37", "ctl00$ContentPlaceHolder1$btnSubmit.y": "9"}

url2 = "http://www.bseindia.com/corporates/corporate_act.aspx"
form_data.update(other_data)
form_data.update(button_data)

print("form_data:")
for k, v in form_data.items():
    print(k, len(v))
    print(v)
print("***********")

y = requests.post(url2, data=form_data, stream=True)
if not y.ok:
    print(y.text)
    sys.exit(1)

html = bs4.BeautifulSoup(y.text, "html.parser")
hidden_elems = html.findAll(attrs={"type": "hidden"})
form_data2 = {}
for el in hidden_elems:
    m = el.attrs
    if "value" in m:
        form_data2[m["name"]] = m["value"]
        print(len(m["value"]))
    else:
        form_data2[m["name"]] = ""

other_data2 = {
    "__EVENTTARGET": "ctl00$ContentPlaceHolder1$lnkDownload",
    "__EVENTARGUMENT": "",
    "myDestination": "#",
    "WINDOW_NAMER": "1",
    "ctl00$ContentPlaceHolder1$hdnCode": "590082",
    "ctl00$ContentPlaceHolder1$hndvalue": "S",
    "ctl00$ContentPlaceHolder1$hnd": "",
    "ctl00$ContentPlaceHolder1$hdnCheck": "",
    "ctl00$ContentPlaceHolder1$date": "exdate",
    "ctl00$ContentPlaceHolder1$txtDate": "",
    "ctl00$ContentPlaceHolder1$txtTodate": "",
    "ctl00$ContentPlaceHolder1$Hidden1": "",
    "ctl00$ContentPlaceHolder1$GetQuote1_smartSearch": "ABB India Limited",
    "ctl00$ContentPlaceHolder1$ddlindustry": "Select--",
    "ctl00$ContentPlaceHolder1$ddlPurpose": "Select",
}

form_data2.update(other_data2)

y2 = requests.post(url2, data=form_data2, stream=True)
if not y2.ok:
    print(y2.text)
    sys.exit(1)
print(y2.text)
