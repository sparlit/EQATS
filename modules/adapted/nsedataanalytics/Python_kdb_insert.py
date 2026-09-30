
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


import MySQLdb
from dateutil.parser import parse
import datetime
import time
from config import *
import numpy as np
from qpython import *
import csv

import logging

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s',
                    filename='/tmp/kdb.log',
                    filemode='w')
demo_file="data_20151123_v1.csv"
with qconnection.QConnection(host=kdb_host,port=kdb_port) as qconn:
    demo_table="test"
    try:
        qconn.open()
        format=typekdb("%s"%demo_table,qconn)
        
        csvopen=csv.reader(file(demo_file))
        for row in csvopen:
            
            if "" in row:
                logging.error(':Length of row %s didnt match column format',",".join(row))
                continue
            logging.info('%s'%",".join(row)) 
            ''' `test1 insert (`$("HDIL-1M");"Z"$("20151123 094042");1800)'''
            data_res=insertkdb(format,row)
            
            print '`%s insert (%s)'%(demo_table,data_res)
            qconn('`%s insert (%s)'%(demo_table,data_res))
    except :
        raise
    finally:
        qconn.close()
        

                        
    


