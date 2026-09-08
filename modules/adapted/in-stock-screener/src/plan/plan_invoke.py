
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
import plan

from operator import itemgetter


# Main caller
program_name = sys.argv[0]

if len(sys.argv) < 6 :
   print "usage: " + program_name + " <debug_level : 1-4> <amfi.csv> <plan.csv> ... "
   sys.exit(1) 

debug_level = int(sys.argv[1])
in_plan_filename = sys.argv[2]
out_filename_phase1 = sys.argv[3]
out_filename_phase2 = sys.argv[4]
out_filename_phase3 = sys.argv[5]
out_filename_phase4 = sys.argv[6]
out_filename_phase5 = sys.argv[7]
	
if debug_level > 1 :
	print 'args :' , len(sys.argv)

indu_comp = 'comp'
ic_name = 'all'

if len(sys.argv) == 9 :
	indu_comp = sys.argv[5]
	ic_name = sys.argv[6]
	ic_name = ic_name.capitalize()

plan = plan.Plan()

plan.set_debug_level(debug_level)

plan.load_amfi_db()
plan.load_plan_data(in_plan_filename)

plan.plan_dump_ticker(out_filename_phase1)
plan.plan_dump_sorted_units(out_filename_phase2)
plan.plan_dump_all(out_filename_phase3)
plan.plan_dump_plus(out_filename_phase4)
plan.plan_dump_zero(out_filename_phase5)

if len(sys.argv) == 8 :
	if indu_comp.lower() == "comp":
		print 'companies count : ', plan.size_comp_data()
		if ic_name == "All":
			plan.print_comp_data()
		else:
			print plan.get_plan_comp_units(ic_name)
	else:
		print 'industries count : ', plan.size_indu_data()
		if ic_name == "All":
			plan.print_indu_data()
		else:
			print plan.get_indu_units(ic_name)