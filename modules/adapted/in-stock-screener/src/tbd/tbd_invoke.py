
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
import tbd 

# Main caller
program_name = sys.argv[0]

if len(sys.argv) < 15 :
   print "usage: " + program_name + " <debug_level : 1-4> <isin-bse.csv> <isin-nse.csv> <amfi.csv> <plan.csv> <demat.csv>... "
   sys.exit(1) 

debug_level = int(sys.argv[1])
screener_aliases_filename = sys.argv[2]
screener_filename = sys.argv[3]

cover_filename= sys.argv[4]
plan_nocond_filename = sys.argv[5]
plan_cond_filename = sys.argv[6]
plan_cond_mos_filename = sys.argv[7]
plan_tbd_cond_filename = sys.argv[8]
plan_tbd_days_nocond_filename = sys.argv[9]
plan_tbd_days_cond_filename = sys.argv[10]
plan_demat_cond_sale_filename = sys.argv[11]
days_1 = int(sys.argv[12])
days_2 = int(sys.argv[13])
mos_1 = int(sys.argv[14])
mos_2 = int(sys.argv[15])
	
if debug_level > 1 :
	print 'args :' , len(sys.argv)

tbd = tbd.Tbd()

tbd.set_debug_level(debug_level)
tbd.load_tbd_data(screener_aliases_filename, screener_filename)

tbd.print_tbd_phase1(cover_filename)
tbd.dump_plan_nocond(plan_nocond_filename)
tbd.dump_plan_cond(plan_cond_filename)
tbd.dump_plan_cond_mos(plan_cond_mos_filename, mos_1)
tbd.dump_plan_tbd_cond(plan_tbd_cond_filename)
tbd.dump_plan_tbd_days_nocond(plan_tbd_days_nocond_filename, days_1)
tbd.dump_plan_tbd_days_cond(plan_tbd_days_cond_filename, days_1)
tbd.dump_plan_demat_cond_sale(plan_demat_cond_sale_filename)