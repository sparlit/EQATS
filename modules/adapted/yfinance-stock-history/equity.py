
import datetime
import pytz

def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
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


#!/usr/bin/env python

import csv
import sqlite3
import os
conn= sqlite3.connect('company.db')
c=conn.cursor()

c.execute('''DROP TABLE IF EXISTS equity''')

c.execute('''CREATE TABLE equity (
    symbol TEXT,
    name TEXT,
    date TEXT,
    face INTEGER)
''')

insertSQL='''INSERT INTO equity VALUES (?,?,?,?)'''
if(os.path.isfile('EQUITY_L.csv')):
    print "file exists"

reader=csv.reader(open('EQUITY_L.csv','rb'))
rownum=0
print reader
for row in reader:
    if rownum==0:
        #rownum+=1
        pass
    else:
        t=(row[0],row[1],row[3],int(row[7]))
        c.execute(insertSQL, t)
    rownum+=1
    
conn.commit()
c.close()    
    