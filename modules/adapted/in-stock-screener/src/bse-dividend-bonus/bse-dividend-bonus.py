
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

# Input Template (equity-target-units.csv) file
# Ignore first 10 lines
# Each entry template
#Industry,Sub Industry, Company,Planned Units,Planned Value,Current Value,TBD Value,TBD Units,TBD %,Last Date,


import sys
import re
import csv
from collections import Counter
from operator import itemgetter

import argparse

parser = argparse.ArgumentParser(description='Process arguments')
# dest= not required as option itself is the destination in args
parser.add_argument('--out_type', default='out_plain', help='out_plain | out_csv')
parser.add_argument('--sort_type', default='sort_frequency', help='sort_frequency')
parser.add_argument('--summary_type', default='summary_yes|summary_no', help='summary_yes')
parser.add_argument('--debug_level', default='0', help='debug level 0|1|2|3', type=int, choices=[0, 1, 2, 3])
parser.add_argument('--dividend_file', nargs='+', dest='dividend_file', help='dividend file')
parser.add_argument('--bonus_file', nargs='+', dest='bonus_file', help='bonus file')

args = parser.parse_args()

# print args


program_name = sys.argv[0]

"""
if len(sys.argv) < 6 :
   print "usage: " + program_name + " <out_plain | out_csv> <sort_frequency| sort_frquency_name_only|sort_amount|company_name_only> <summary_yes|sumary_no> <debug_level : 1-4> <dividend-bse.csv> ... "
   sys.exit(1) 

out_type= sys.argv[1]
sort_type= sys.argv[2]
summary_type= sys.argv[3]
debug_level= int(sys.argv[4])
in_filenames= sys.argv[5:]
"""

out_type= args.out_type 
sort_type= args.sort_type 
summary_type= args.summary_type 
debug_level= args.debug_level 
bonus_filenames = args.bonus_file
dividend_filenames = args.dividend_file

# print 'bonus_filenames', bonus_filenames
# print 'dividend_filenames', dividend_filenames

# Error-1, Warn-2, Log-3
companies=[]
industries=[]
sectors=[]
dividend_amount={}
bonus_share={}
company_aliases={}
total_dividend = 0

def load_dividend(row, company_name, purpose):
	try:
		m = re.search("(.*)(Dividend - Rs. -)(.*)", purpose)
		if m.group(2) != "Dividend - Rs. -" :
			if debug_level > 1:
				print 'no dividend match', row 
			return
		else:
			companies.append(company_name)

        	if company_name in dividend_amount.keys():
			dividend_amount[company_name] =  int(dividend_amount[company_name]) + int(float(m.group(3)))
		else:
			dividend_amount[company_name] =  int(float(m.group(3)))
	except NameError :
		if debug_level > 1:
			print 'NameError', row
	except AttributeError:
		if debug_level > 1:
			print 'AttributeError', row

def load_bonus(row, company_name, purpose):
	try:
		m = re.search("(Bonus issue)(.*)", purpose)
		if m.group(1) != "Bonus issue":
			if debug_level > 1:
				print 'no bonus match', row 
			return
		else:
			companies.append(company_name)

        	if company_name in bonus_share.keys():
			bonus_share[company_name] =  bonus_share[company_name] +' &' + m.group(2)
		else:
			bonus_share[company_name] =  m.group(2) 
	except NameError :
		if debug_level > 1:
			print 'NameError', row
	except AttributeError:
		if debug_level > 1:
			print 'AttributeError', row


def load_row(data_type, row):
	security_code, security_name, company_name, ex_date, purpose, record_date, bc_state_date, bc_end_date, nd_start_date, nd_end_date, actual_payment_date = row
	company_name = company_name.capitalize()
	company_name = company_name.strip()
	if data_type == "d":
		load_dividend(row, company_name, purpose)
	if data_type == "b":
		load_bonus(row, company_name, purpose)
	
	
def load_data(data_type, in_filenames):
	for in_filename in in_filenames:
		with open(in_filename, 'r') as csvfile:
			reader = csv.reader(csvfile)
			for row in reader:
				load_row(data_type, row)


load_data('d', dividend_filenames)
load_data('b', bonus_filenames)

companies.sort()

if sort_type == "company_name_only": 
	for cname in sorted(set(companies)):
		print cname

# calculate frequency of occurence of each company
comp_freq = Counter(companies)

if debug_level > 1:
	print(comp_freq)

if sort_type == "sort_frequency_name_only" :
	for key, value in sorted(comp_freq.items()):
		print key

if sort_type == "sort_frequency" :
	print 'company_name, company_frequency, company_dividend, company_bonus'
	try:
		for key, value in sorted(comp_freq.items(), key=itemgetter(1)):
			if key in bonus_share.keys():
				bonus_column = bonus_share[key]
			else:
				bonus_column=""
			
			
			if key in dividend_amount.keys():
				dividend_column = dividend_amount[key]
			else:
				dividend_column=0
			
			if out_type == "out_csv" :
				print key,',', value, ',', dividend_column, ',', bonus_column
			else:
				print key, value, dividend_column, bonus_column
	except KeyError:
		print 'failed key : ', key 

if sort_type == "sort_amount" :
	print 'company_name, company_dividend, company_bonus, company_frequency'
	try:
		for key, value in sorted(dividend_amount.items(), key=itemgetter(1)):
			if key in bonus_share.keys():
				bonus_column = bonus_share[key]
			else:
				bonus_column=""
			
			if key in dividend_amount.keys():
				dividend_column = dividend_amount[key]
			else:
				dividend_column=0
			
			if out_type == "out_csv" :
				print key,',', value, ',', bonus_column, ',', comp_freq[key]
			else:
				print key, value, bonus_column, comp_freq [key]
	except KeyError:
		print 'failed key :', key 