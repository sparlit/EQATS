
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
import dividend

from operator import itemgetter

# Main caller
program_name = sys.argv[0]

if len(sys.argv) < 6 :
   print "usage: " + program_name + " <debug_level : 1-4> <amfi.csv> <dividend.csv> ... "
   sys.exit(1) 

debug_level = int(sys.argv[1])
in_amfi_filename = sys.argv[2]
in_aliases_filename = sys.argv[3]
out_filename_phase0 = sys.argv[4]
out_filename_phase1 = sys.argv[5]
out_filename_phase2 = sys.argv[6]
out_filename_phase3 = sys.argv[7]
out_filename_phase4 = sys.argv[8]
in_dividend_filenames = sys.argv[9:]
	
if debug_level > 1 :
	print 'args :' , len(sys.argv)
        print 'in_dividend_filenames :', in_dividend_filenames

dividend = dividend.Dividend()

dividend.set_debug_level(debug_level)

dividend.load_amfi_db()
#dividend.load_amfi_data(in_amfi_filename)
dividend.load_aliases_data(in_aliases_filename)
dividend.load_dividend_data(in_dividend_filenames)

dividend.dump_orig(out_filename_phase0)
dividend.print_phase1(out_filename_phase1)
dividend.print_phase2(out_filename_phase2)
dividend.print_phase3(out_filename_phase3)
dividend.print_phase4(out_filename_phase4)