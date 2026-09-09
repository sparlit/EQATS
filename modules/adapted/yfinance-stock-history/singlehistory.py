
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
import urllib2
import httplib

conn= sqlite3.connect('history.db')
c=conn.cursor()

inp=str(raw_input())

c.execute('''DROP TABLE IF EXISTS '''+inp)

c.execute('''CREATE TABLE ''' +inp+ ''' (
    date TEXT,
    open TEXT,
    high TEXT,
    low TEXT,
    close TEXT,
    volume TEXT)
''')

insertSQL='''INSERT INTO '''+inp+''' VALUES (?,?,?,?,?,?)'''

response = urllib2.urlopen("http://ichart.finance.yahoo.com/table.csv?s="+inp+".NS&a=07&b=12&c=2002&d=01&e=6&f=2011&g=d&ignore=.csv")

csvfile=response.read()
#print csvfile
fout=open('temp.csv','w')
fout.write(csvfile)
fout.close()
reader=csv.reader(open('temp.csv','rb'))
os.remove('temp.csv')
rownum=0
#print reader
for row in reader:
    if rownum==0:
        #rownum+=1
        pass
    else:
        print row
        t=(row[0],row[1],row[2],row[3],row[4],row[5])
        c.execute(insertSQL, t)
    rownum+=1
    
conn.commit()
c.close()    
    


