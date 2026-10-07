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


import csv
import datetime
import logging
import os
import urllib.error as error
import urllib.request as rq

from bs4 import BeautifulSoup


class Crawler:
    def __init__(self):
        # log errors for pages not found
        logging.basicConfig(filename="errorlog/error.log", level=logging.ERROR)

    def getURLData(self, date):
        """
        the list dailyShares contains all the companies shares of that day
        shareDetails list contains all the details of a particular company .i.e name, code , volume e.t.c
        shareElement list makes up the Share Details which makes up the dailyShares list
        """
        self.dailyShares = []
        self.date = str(date)
        self.createFolder("data/daily/" + self.date[0:4])
        url = "https://live.mystocks.co.ke/price_list/" + self.date
        try:
            html = rq.urlopen(url).read()
            self.soup = BeautifulSoup(html, "lxml")
            self.extractURLData()
        except error.HTTPError as e:
            now = datetime.datetime.now()
            errorMessage = str(now) + " - " + str(e) + " Date: " + str(self.date)
            print("Please check error log file in errorlog directory")
            logging.error(errorMessage)

    # Extract the data from the page requested
    def extractURLData(self):
        table = self.soup.find("table", {"class": "tblHoverHi"})
        for row in table.findAll("tr"):
            shareDetails = []
            shareElements = []
            for element in row.findAll("td"):
                # the share categories i.e banking, manufacturing
                for heading in element.findAll("h3"):
                    _heading = heading.string
                # the share company name
                for item in element.findAll("a"):
                    shareElements.append(item.string)
                # the shares details i.e price,volume
                if element.string != heading.string:
                    shareElements.append(element.string)
            # removes empty and None arrays, clean up from html extracted data
            if shareElements != [] and len(shareElements) > 1:
                # code
                shareDetails.append(shareElements[0])
                # name
                shareDetails.append(shareElements[1])
                # lowest price
                if shareElements[5] is None or shareElements[5] == "-":
                    shareDetails.append(shareElements[5])
                else:
                    shareDetails.append(float(shareElements[5].replace(",", "")))
                # highest price
                if shareElements[6] is None or shareElements[6] == "-":
                    shareDetails.append(shareElements[6])
                else:
                    shareDetails.append(float(shareElements[6].replace(",", "")))
                # price
                if shareElements[7] is None or shareElements[7] == "-":
                    shareDetails.append(shareElements[7])
                else:
                    shareDetails.append(float(shareElements[7].replace(",", "")))
                # previous day's price
                if shareElements[8] is None or shareElements[8] == "-":
                    shareDetails.append(shareElements[8])
                else:
                    shareDetails.append(float(shareElements[8].replace(",", "")))
                # volume
                if (shareElements[12] is None) or (shareElements[12] == "-"):
                    shareDetails.append(shareElements[12])
                else:
                    shareDetails.append(str(shareElements[12].replace(",", "")))
                self.dailyShares.append(shareDetails)
        self.saveCSV()

    # creates a folder for either the year or month if it doesnt exist
    def createFolder(self, path):
        folder = os.path.isdir(path)
        if folder is False:
            os.mkdir(path)

    # saves the data extracted in a csv
    def saveCSV(self):
        year = self.date[0:4]
        month = self.date[4:6]
        path = "data/daily/" + str(year) + "/" + month + "/"
        folder = os.path.isdir(path)
        if not folder:
            os.mkdir(path)
        myFile = open(path + str(self.date) + ".csv", "w")
        writeFile = csv.writer(myFile, delimiter=";")
        writeFile.writerow(
            [
                "Code",
                "Name",
                "Lowest Price of the Day",
                "Highest Price of the Day",
                "Closing Price",
                "Previous Day Closing Price",
                "Volume Traded",
            ],
        )
        writeFile.writerows(self.dailyShares)
        myFile.close()
