
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

# Developer : Surinder Kumar 
#
# Login to icici bank account using net banking
# My accounts -> Bank Accounts -> View Detailed Statement
# Transaction Date from ... maximum 1 year period
# 01-04-2017 to 31-03-2018
# Advanced Search : Transaction Type : Credit
# Get Statement
# At bottom :  Download details as XLS file
# Save it as OpTransactionHistory17-04-2018.xls (automatic name)
# Open it and Delete first 12 lines
#   ** This remove personal details information (Name and Account number)
#   ** line # 4 'Account Number' 
#   ** line # 12 'Transactions list' 
# Clear contents of Balance Column (Last column)
# Save it as CSV (Comma delimited) (*.csv) : OpTransactionHistory17-04-2018.csv file
# Upload OpTransactionHistory17-04-2018.csv to stock-market/fy17-18/

# Handle INT independent as a member of AMR INT
# Handle company with space and no space

import os
import sys
import re
import csv
from collections import Counter
from operator import itemgetter

program_name = sys.argv[0]

if len(sys.argv) < 6 :
   print "usage: " + program_name + " <out_plain | out_csv> <sort_amount|sort_frequency|sort_name|name_only> <summary_yes|sumary_no> <debug_level : 1-4> <op-txn-hist.csv> ... "
   sys.exit(1) 

out_type= sys.argv[1]
sort_type= sys.argv[2]
summary_type= sys.argv[3]
debug_level= int(sys.argv[4])
in_filenames= sys.argv[5:]
# Error-1, Warn-2, Log-3
companies=[]
company_real_name_db=[]
dividend_amount={}
company_aliases={}
total_dividend = 0
# conglomerate name db
cong_name_db=[]
PROJ_LOCAL_DATA_LOC=os.getenv('PROJ_LOCAL_DATA_LOC')
PROJ_PROFILE_REPORTS_LOC=os.getenv('PROJ_PROFILE_REPORTS_LOC')
# company_aliases_filename = PROJ_LOCAL_DATA_LOC + '/other-data/dividend-company-name-aliases.csv'
company_aliases_filename = PROJ_LOCAL_DATA_LOC + '/other-data/dividend-company-ticker-aliases.csv'
cong_filename = PROJ_LOCAL_DATA_LOC + '/other-data/conglomerate-name.txt'
comp_filename = PROJ_PROFILE_REPORTS_LOC + '/plan-reports/plan-reports-sort-name.csv'

def ignore_txn(line, txn_remarks):
        # match for search at begining
	# NEFT or RTGS or MMT - Mobile money Transfer	
	if re.match('NEFT-|RTGS-|MMT/', txn_remarks):
		if debug_level > 2:
			print 'NEFT-/RTGS-/MMT skipped' + line
		return True 
	
	# CASH deposit
	if re.match('BY CASH.*', txn_remarks):
		if debug_level > 2:
			print 'CASH skipped' + line
		return True 
	
 	# Interest paid	- anywhere in string
	if re.search('.*:Int\.Pd:.*', txn_remarks):
		if debug_level > 2:
			print 'Int.Pd skipped' + line
		return True 
	
 	# APBS / BLPGCM : Aadhaar Payment Bridge System for LPG Subsidy
	if re.match('APBS/.*', txn_remarks):
		if debug_level > 2:
			print 'APBS skipped' + line
		return True 
	
	return False 


def normalize_company_name(company_name):
	# capitalize
	company_name = company_name.capitalize()
	# remove . (TCS.) and hyphen (2017-2018)
	company_name = re.sub('\.|-','', company_name)
	# remove 1STINTDIV, 2NDINTDIV, 3RDINTDIV
	company_name = re.sub('1st|2nd|3rd','', company_name)
	# remove FINALDIV etc
	company_name = re.sub('final div|final','', company_name)
	company_name = re.sub('fin div|findiv','', company_name)
	company_name = re.sub('int div|intdiv','', company_name)
	# remove words like DIV, DIVIDEND
	company_name = re.sub('div\.|dividend|div','', company_name)
	company_name = re.sub('limited|ltd','ltd', company_name)
	# remove any numbers like year 2017, 2018 etc
	company_name = re.sub('\d*','', company_name)
	# remove any characters after (  : colgatepalomolive (india)
	company_name = re.sub('\(.*','', company_name)
	# convert multiple space to single space
	company_name = re.sub(' +', ' ', company_name)
	# remove leading and trailing space
	company_name = company_name.strip()
	'''
	# remove incomplete word
	if len(company_name) == 20:
	# remove last word which will be mostly incomplete
	company_name = company_name.rsplit(' ', 1)[0] 
	'''
	company_name = resolve_alias(company_name)
	company_name = resolve_real_company_name_db(company_name)
	return company_name

def load_aliases():
	with open(company_aliases_filename, 'r') as csvfile:
		reader = csv.reader(csvfile)
		for row in reader:
			name_alias, ticker = row
			name_alias = name_alias.strip().capitalize()
			ticker = ticker.strip().upper()
			if debug_level > 2: 
				print 'alias ', name_alias, 'ticker ', ticker 
			company_aliases[name_alias] = ticker 

def resolve_alias(company_name):
	if company_name in company_aliases.keys():
		company_name = company_aliases[company_name]
	return company_name

def load_real_company_name_db():
	comp_name_file_obj = open(comp_filename, 'r')
	for row in comp_name_file_obj:
		name_real = row
		name_real = name_real.strip()
		name_real = name_real.capitalize()
		if debug_level > 2:
			print 'real name', name_real 
		company_real_name_db.append(name_real)

def load_conglomerate_name_db():
	cong_name_file_obj = open(cong_filename, 'r')
	for row in cong_name_file_obj:
		name_cong = row
		name_cong = name_cong.strip()
		name_cong = name_cong.capitalize()
		if debug_level > 2:
			print 'cong name', name_cong
		cong_name_db.append(name_cong)

def resolve_real_company_name_db(company_name):
	# avoid tinkering conglomerates with same prefix 
	for cong_name in cong_name_db:
		if company_name.find(cong_name, 0) >= 0:
			return company_name 
	for real_company_name in company_real_name_db:
		if company_name.find(real_company_name, 0) >= 0:
			if debug_level > 2:
				print 'replaced from ', company_name, 'to ', real_company_name
			company_name = real_company_name
			return company_name
	return company_name

def parse_line(line):
	# Replace Limited, with just Limited to avoid split error : ValueError
	line = re.sub(r'Limited,','Limited',line)
	line = re.sub(r'Ltd,','Ltd',line)
	
	try:
	  empty1, sno, value_date, txn_date, cheque, txn_remarks, wdraw_amount, deposit_amount, balance, empty2  = line.split(",")
	except ValueError:
          print 'ValueError ', line

	# avoid cases where txn_remarks itself is double quoted
	txn_remarks = re.sub(r'"','', txn_remarks);

        if txn_remarks == "":
		if line != "":
                	if debug_level > 1:
			   print 'empty ' + line
		return	

	if debug_level > 2:
        	# print 'txn_remarks '+ txn_remarks
		pass	

	if ignore_txn(line, txn_remarks):
                if debug_level > 2:
			print 'ignored ', txn_remarks
		return	
	
	if re.match('ACH/.*|CMS/.*', txn_remarks):
		# print txn_date, txn_remarks, deposit_amount
                try:
                	remarks_arr = txn_remarks.split('/')
                        deposit_way = remarks_arr[0] 
                        company_name = remarks_arr[1] 
                        comment_str = remarks_arr[2] 
                        # ignore rest
		except ValueError:
			print 'ValueError ' + txn_remarks

		# print company_name, deposit_amount
		company_name = normalize_company_name(company_name)
		if debug_level > 2: 
			print 'normalized :', company_name

                companies.append(company_name)
                if company_name in dividend_amount.keys():
			if debug_level > 1:                 
                        	print 'dividend amount :', dividend_amount[company_name]
                        	print 'deposit amount :', deposit_amount 
                	dividend_amount[company_name] = int(dividend_amount[company_name]) + int(float(deposit_amount))
                else:
			dividend_amount[company_name] = int(float(deposit_amount))
                        
               
		return	
	
	if debug_level > 1:
		print 'Unknown skipped' + line
	return	

def read_lines(file_obj):
	for line in file_obj:
		parse_line(line)

def scan_files():
	for in_file_name in in_filenames:
		file_obj = open (in_file_name, "r")
		read_lines(file_obj)


# main routine

# load real company name
load_real_company_name_db()

# load conglomerate name
load_conglomerate_name_db()

# load aliases
load_aliases()

# load real company names
scan_files();

# sort companies
companies.sort()

for value in dividend_amount.values() :
	total_dividend += value


# calculate frequency of occurence of each company
comp_freq = Counter(companies)

if debug_level > 1:
	print(comp_freq)

if sort_type == "name_only" :
	for key, value in sorted(comp_freq.items()):
		print key


if sort_type == "sort_name" :
	for key, value in sorted(comp_freq.items()):
		if out_type == "out_csv" :
			print key,',', value, ',', dividend_amount[key] 
		else:
			print key, value, dividend_amount[key] 
elif sort_type == "sort_frequency" :
	for key, value in sorted(comp_freq.items(), key=itemgetter(1)):
		if out_type == "out_csv" :
			print key,',', value, ',', dividend_amount[key] 
		else:
			print key, value, dividend_amount[key]
elif sort_type == "sort_amount":
	for key, value in sorted(dividend_amount.items(), key=itemgetter(1)) :
		if out_type == "out_csv" :
			print key,',', value
		else:
			print key, value

if summary_type == "summary_yes" and sort_type == "sort_name" :
	if out_type == "out_csv" :
		print 'total dividend amount:  ,' , ' 0 ,' , total_dividend 
		print 'total dividend entries: ,' , ' 0 ,' , len(companies)
		print 'total companies count:  ,' , ' 0 ,' , len(comp_freq)
	else:
		print 'total dividend amount:  ' ,  ' 0 ' , total_dividend 
		print 'total dividend entries: ' ,  ' 0 ' , len(companies)
		print 'total companies count:  ' ,  ' 0 ' , len(comp_freq)

if summary_type == "summary_yes" and sort_type == "sort_frequency" :
	if out_type == "out_csv" :
		print 'total dividend amount:  ,' , ' 0 ,' , total_dividend 
		print 'total dividend entries: ,' , ' 0 ,' , len(companies)
		print 'total companies count:  ,' , ' 0 ,' , len(comp_freq)
	else:
		print 'total dividend amount:  ' ,  ' 0 ' , total_dividend 
		print 'total dividend entries: ' ,  ' 0 ' , len(companies)
		print 'total companies count:  ' ,  ' 0 ' , len(comp_freq)

if summary_type == "summary_yes" and sort_type == "sort_amount" :
	if out_type == "out_csv" :
		print 'total dividend amount:  ,' ,  total_dividend 
		print 'total dividend entries: ,' ,  len(companies)
		print 'total companies count:  ,' ,  len(comp_freq)
	else:
		print 'total dividend amount:  ' ,  total_dividend 
		print 'total dividend entries: ' ,  len(companies)
		print 'total companies count:  ' ,  len(comp_freq)
