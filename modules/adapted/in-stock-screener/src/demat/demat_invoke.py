
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


#!/usr/bin/python

import sys
import re
import csv
import traceback

import demat

# Main caller
program_name = sys.argv[0]

if len(sys.argv) < 6 :
   print "usage: " + program_name + " <debug_level : 1-4> <demat.csv> ... "
   sys.exit(1) 

debug_level = int(sys.argv[1])
txn_file = sys.argv[2]
summary_file = sys.argv[3]
out_file_1 = sys.argv[4]
out_file_2 = sys.argv[5]
out_file_3 = sys.argv[6]
out_file_4 = sys.argv[7]
	
if debug_level > 1 :
	print 'args :' , len(sys.argv)

demat = demat.Demat()

demat.set_debug_level(debug_level)
demat.demat_txn_load_data(txn_file)
demat.demat_summary_load_data(summary_file)
demat.print_phase1(out_file_1)
demat.print_phase2(out_file_2)
demat.print_phase3(out_file_3)
demat.print_phase4(out_file_4)