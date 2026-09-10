
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
import screener

# Main caller
program_name = sys.argv[0]

if len(sys.argv) < 8 :
   print "usage: " + program_name + " <debug_level : 1-4> <screener-data.csv> ... "
   sys.exit(1) 

debug_level = int(sys.argv[1])
isin_bse_filename = sys.argv[2]
isin_nse_filename = sys.argv[3]
in_amfi_filename = sys.argv[4]
sc_aliases_filename = sys.argv[5]
sc_data_1_filename = sys.argv[6]
sc_data_2_filename = sys.argv[7]
out_filename_phase1 = sys.argv[8]
out_filename_phase2 = sys.argv[9]
	
if debug_level > 1 :
	print 'args :' , len(sys.argv)

screener = screener.Screener()

screener.set_debug_level(debug_level)

screener.load_isin_data_both(isin_bse_filename, isin_nse_filename)
screener.load_amfi_db()
# screener.load_amfi_data(in_amfi_filename)

screener.load_screener_name_aliases(sc_aliases_filename)
screener.load_screener_data(sc_data_1_filename)
screener.load_screener_data(sc_data_2_filename)

screener.print_phase1(out_filename_phase1)
screener.print_phase2(out_filename_phase2)