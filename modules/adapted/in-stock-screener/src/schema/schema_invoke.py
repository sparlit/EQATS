
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
import schema

# Main caller
program_name = sys.argv[0]

if len(sys.argv) < 3 :
   print "usage: " + program_name + " <debug_level : 1-4> <schema.csv> ... "
   sys.exit(1) 

debug_level = int(sys.argv[1])
schema_filename = sys.argv[2]
#db_filename = sys.argv[3]
	
if debug_level > 1 :
	print 'args :' , len(sys.argv)

schema = schema.Schema()

schema.set_debug_level(debug_level)

schema.create_schema(schema_filename)
# schema.create_schema(db_filename, schema_filename)

# schema.print_phase1(out_filename)