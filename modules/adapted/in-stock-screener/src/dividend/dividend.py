
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

from collections import Counter
from operator import itemgetter

import cutil.cutil

from amfi.amfi import * 

class Dividend(Amfi):

	def __init__(self):
		super(Dividend, self).__init__()
		self.multiplier	= 0 
		self.debug_level = 0 
		self.last_row = "" 
		self.companies=[]
		self.company_real_name_db=[]
		self.dividend_amount={}
		self.company_aliases={}
		self.company_orig={}
		self.total_dividend = 0
		# conglomerate name db
		self.cong_name_db=[]
		print 'init : Dividend'

	def set_debug_level(self, debug_level):
		self.debug_level = debug_level

	def ignore_txn(self, line, txn_remarks):
		# match for search at begining
		# NEFT or RTGS or MMT - Mobile money Transfer	
		if re.match('NEFT-|RTGS-|MMT/', txn_remarks):
			if self.debug_level > 2:
				print 'NEFT-/RTGS-/MMT skipped' + line
			return True 
	
		# CASH deposit
		if re.match('BY CASH.*', txn_remarks):
			if self.debug_level > 2:
				print 'CASH skipped' + line
			return True 
	
		# Interest paid	- anywhere in string
		if re.search('.*:Int\.Pd:.*', txn_remarks):
			if self.debug_level > 2:
				print 'Int.Pd skipped' + line
			return True 
	
		# APBS / BLPGCM : Aadhaar Payment Bridge System for LPG Subsidy
		if re.match('APBS/.*', txn_remarks):
			if self.debug_level > 2:
				print 'APBS skipped' + line
			return True 
	
		return False 

	def normalize_company_name(self, company_name):
		# old orig name
		orig_name = company_name
		# capitalize
		company_name = company_name.capitalize()
		# remove . (TCS.) and hyphen (2017-2018), Lupin$
		company_name = re.sub('\.|-|\$','', company_name)
		# remove 1STINTDIV, 2NDINTDIV, 3RDINTDIV
		company_name = re.sub('1st|2nd|3rd','', company_name)
		# remove FINALDIV etc
		company_name = re.sub('final div|final','', company_name)
		company_name = re.sub('fin div|findiv','', company_name)
		company_name = re.sub('int div|intdiv','', company_name)
		# remove words like DIV, DIVIDEND
		company_name = re.sub('div\.|dividend|div','', company_name)
		# remove any numbers like year 2017, 2018 etc
		company_name = re.sub('\d*','', company_name)
		# remove any characters after (  : colgatepalomolive (india)
		company_name = re.sub('\(.*','', company_name)
		# convert multiple space to single space
		company_name = re.sub(' +', ' ', company_name)
		# remove leading and trailing space
		company_name = company_name.strip()
		
		company_name = self.resolve_alias(company_name)
	
		# remove limited, ltd etc
		company_name = re.sub('limited|ltd','', company_name)

		# remove incomplete word
		# remove last word which will be mostly incomplete
		if len(company_name) == 20:
			company_name = company_name.rsplit(' ', 1)[0] 
			
		# remove of india 
		company_name = re.sub(' of india','', company_name)
		# remove india 
		company_name = re.sub(' india','', company_name)
		
		company_name = self.resolve_real_company_name_db(company_name)
		self.company_orig[company_name] = orig_name
		if self.debug_level > 1:
			print 'orig name', orig_name, 'new name', company_name
		return company_name

	def load_real_company_name_db():
		comp_name_file_obj = open(comp_filename, 'r')
		for row in comp_name_file_obj:
			name_real = row
			name_real = name_real.strip()
			name_real = name_real.capitalize()
			if debug_level > 2:
				print 'real name', name_real 
			self.company_real_name_db.append(name_real)

	def load_conglomerate_name_db():
		cong_name_file_obj = open(cong_filename, 'r')
		for row in cong_name_file_obj:
			name_cong = row
			name_cong = name_cong.strip()
			name_cong = name_cong.capitalize()
			if debug_level > 2:
				print 'cong name', name_cong
			self.cong_name_db.append(name_cong)
	
	def resolve_alias(self, company_name):
		if company_name in self.company_aliases.keys():
			company_name = self.company_aliases[company_name]
		return company_name

	def resolve_real_company_name_db(self, company_name):
		# avoid tinkering conglomerates with same prefix 
		for cong_name in self.cong_name_db:
			if company_name.find(cong_name, 0) >= 0:
				return company_name 
		for real_company_name in self.company_real_name_db:
			if company_name.find(real_company_name, 0) >= 0:
				if debug_level > 2:
					print 'replaced from ', company_name, 'to ', real_company_name
				company_name = real_company_name
				return company_name
		return company_name

	def load_dividend_row(self, line):
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
	
		if self.debug_level > 1:
			print 'txn_remarks '+ txn_remarks
			# pass	
	
		if self.ignore_txn(line, txn_remarks):
			if self.debug_level > 2:
				print 'ignored ', txn_remarks
			return	
	
		if re.match('ACH/.*|CMS/.*', txn_remarks):
			# print txn_date, txn_remarks, deposit_amount
			try:
				remarks_arr = txn_remarks.split('/')
				deposit_way = remarks_arr[0] 
				company_name = remarks_arr[1] 
				if len(remarks_arr) >= 3:
					comment_str = remarks_arr[2]
				# ignore rest
			except ValueError:
				print 'ValueError ' + txn_remarks
	
			# print company_name, deposit_amount
			company_name = self.normalize_company_name(company_name)
			if self.debug_level > 1: 
				print 'normalized :', company_name
			isin  = self.get_amfi_isin_by_name(company_name)
			if self.debug_level > 1: 
				print ' isin :', isin 
			ticker = self.get_amfi_ticker_by_code(isin)
			if self.debug_level > 1: 
				print ' ticker :', ticker
			if ticker != "UNK_TICKER" :
				company_name = ticker
	
			self.companies.append(company_name)
	
			if company_name in self.dividend_amount.keys():
				if self.debug_level > 1:                 
					print 'dividend amount :', self.dividend_amount[company_name]
					print 'deposit amount :', deposit_amount 
				self.dividend_amount[company_name] = int(self.dividend_amount[company_name]) + int(float(deposit_amount))
			else:
				self.dividend_amount[company_name] = int(float(deposit_amount))
			return	
	
		if self.debug_level > 1:
			print 'Unknown skipped' + line
		return	

	def load_dividend_data(self, in_filenames):
		for in_filename in in_filenames:
			if self.debug_level > 1:
				print  'div file', in_filename
			file_obj = open (in_filename, "r")
			for line in file_obj:
				if self.debug_level > 1:
					print 'div line', line
				self.load_dividend_row(line)
		print 'loaded dividend', len (self.dividend_amount)

	def load_aliases_row(self, row):
		try:
			name_alias, ticker = row
		except ValueError:
			print 'ValueError ', row 
		
		name_alias = name_alias.strip().capitalize()
		ticker = ticker.strip().upper()
		if self.debug_level > 2: 
			print 'alias ', name_alias, 'ticker ', ticker 
		self.company_aliases[name_alias] = ticker 

	def load_aliases_data(self, in_filename):
		with open(in_filename, 'r') as csvfile:
			reader = csv.reader(csvfile)
			for row in reader:
				self.load_aliases_row(row)
		print 'loaded aliases', len (self.company_aliases)

	def dump_orig(self, out_filename):
		if self.debug_level > 2: 
			print self.company_orig
		lines = []
		fh = open(out_filename, "w") 
		for comp_name in self.company_orig.keys():
			p_str = comp_name 
			p_str += ',' 
			p_str += self.company_orig[comp_name] 
			p_str += '\n'
			lines.append(p_str)
		fh.writelines(lines)
		return
		
	# sort_type 
	def print_phase0(self, out_filename, sort_type):
		# sort companies
		self.companies.sort()
	
		total_dividend = 0
		for value in self.dividend_amount.values() :
			total_dividend += value
	
		# calculate frequency of occurence of each company
		comp_freq = Counter(self.companies)
	
		if self.debug_level > 1:
			print(comp_freq)
	
		lines = []
		fh = open(out_filename, "w") 
	
		if sort_type == "name_only":
			for key, value in sorted(comp_freq.items()):
				p_str = key
				p_str += '\n'
				lines.append(p_str)
		elif sort_type == "sort_name" :
			for key, value in sorted(comp_freq.items()):
				p_str = key
				p_str += ','
				p_str += str(value)
				p_str += ','
				p_str += str(self.dividend_amount[key])
				p_str += '\n'
				lines.append(p_str)
		elif sort_type == "sort_frequency" :
			for key, value in sorted(comp_freq.items(), key=itemgetter(1)):
				p_str = key
				p_str += ','
				p_str += str(value)
				p_str += ','
				p_str += str(self.dividend_amount[key])
				p_str += '\n'
				lines.append(p_str)
		elif sort_type == "sort_amount":
			for key, value in sorted(self.dividend_amount.items(), key=itemgetter(1)) :
				p_str = key
				p_str += ','
				p_str += str(value)
				p_str += ','
				p_str += str(self.dividend_amount[key]) 
				p_str += '\n'
				lines.append(p_str)
		fh.writelines(lines)
		return

	# name_only 
	def print_phase1(self, out_filename):
		self.print_phase0(out_filename, "name_only")

	# sort_name 
	def print_phase2(self, out_filename):
		self.print_phase0(out_filename, "sort_name")

	# sort_frequency
	def print_phase3(self, out_filename):
		self.print_phase0(out_filename, "sort_frequency")

	# sort_amount 
	def print_phase4(self, out_filename):
		self.print_phase0(out_filename, "sort_amount")