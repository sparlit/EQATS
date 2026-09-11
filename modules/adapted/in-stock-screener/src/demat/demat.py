
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
import operator

import cutil.cutil

from database.database import *

class Demat(Database):

	def __init__(self):
		super(Demat, self).__init__()
		self.company_name = {}
		self.demat_txn_last_type = {}
		self.demat_txn_buy_qty = {}
		self.demat_txn_buy_price = {}
		self.demat_txn_sale_qty = {}
		self.demat_txn_sale_price = {}
		self.demat_txn_last_date = {}
		self.demat_txn_list = {}
		self.demat_summary_qty = {}
		self.demat_summary_acp	= {}
		self.demat_summary_upl_pct = {}
		self.demat_summary_hold_units	= {}
		self.debug_level = 0 
		print 'init : Demat'

	def set_debug_level(self, debug_level):
		self.debug_level = debug_level 


	def demat_txn_load_row(self, row):
		try:
			row_list = row
			# skip header
			if row_list[0] == 'Stock Symbol':
				return
			comp_name = row_list[1]
			isin_code   = (row_list[2]).upper().strip()
			txn_type = row_list[3]
			txn_qty = row_list[4]
			txn_price = str(int(round(float(row_list[5]))))
			txn_date = row_list[12]
			
			p_str = isin_code 
			p_str += ','
			p_str += comp_name 
			p_str += ','
			p_str += txn_type
			p_str += ','
			p_str += txn_qty
			p_str += ','
			p_str += txn_price
			p_str += ','
			p_str += txn_date
			p_str += '\n'
			
			if self.debug_level > 1:
				print p_str
			
			if isin_code in self.demat_txn_list:	
				self.demat_txn_list[isin_code] += p_str	
			else:
				self.demat_txn_list[isin_code] = p_str	
				
			self.company_name[isin_code] = cutil.cutil.normalize_comp_name(comp_name)
			if txn_type == "Buy":
				if isin_code in self.demat_txn_buy_qty:
					self.demat_txn_buy_qty[isin_code] += int(txn_qty)
					self.demat_txn_buy_price[isin_code]    += int(round(float(txn_price))) * int(txn_qty)
				else:
					self.demat_txn_buy_qty[isin_code] = int(txn_qty) 
					self.demat_txn_buy_price[isin_code]    = int(round(float(txn_price))) * int(txn_qty)
			else:
				if isin_code in self.demat_txn_sale_qty:
					self.demat_txn_sale_qty[isin_code] += int(txn_qty)
					self.demat_txn_sale_price[isin_code]    += int(round(float(txn_price))) * int(txn_qty)
				else:
					self.demat_txn_sale_qty[isin_code] = int(txn_qty)
					self.demat_txn_sale_price[isin_code]    = int(round(float(txn_price))) * int(txn_qty)
		
			# skip updating bonus entries	
			if txn_price != 0:	
				self.demat_txn_last_type[isin_code]  = txn_type 
				self.demat_txn_last_date[isin_code]  = txn_date 
	
		except:
			print "demat Unexpected error:", sys.exc_info()


	def demat_summary_load_row(self, row):
		try:
			row_list = row
			# skip header
			if row_list[0] == 'Stock Symbol':
				return
			comp_name = row_list[1]
			isin_code   = (row_list[2]).upper().strip()
			qty = row_list[3]
			acp = row_list[4]
			cmp = row_list[5]
			pct_change = row_list[6] 
			value_cost = row_list[7] 
			value_market = row_list[8] 
			realized_pl = row_list[9] 
			unrealized_pl = row_list[10] 
			unrealized_pl_pct = row_list[11] 
			unused1 = row_list[12]
			self.demat_summary_qty[isin_code] = qty 
			self.demat_summary_acp[isin_code] = acp
			self.demat_summary_upl_pct[isin_code] = unrealized_pl_pct 
			if qty > 0:
				hold_units = int(round(float(qty)*float(acp)/1000))
			else:
				hold_units = 0
			# store 
			self.demat_summary_hold_units[isin_code] = hold_units
		except:
			print "demat_summary_load_row Unexpected error:", sys.exc_info(), row
			
	def demat_txn_load_data(self, in_filename):
		table = "demat_txn"
		row_count = self.db_table_count_rows(table)
		if row_count == 0:
			self.demat_txn_insert_data(in_filename)
		else:
			print 'demat_txn data already loaded in db', row_count
		print 'display db data'
		self.demat_txn_load_db()


	def demat_summary_load_data(self, in_filename):
		table = "demat_summary"
		row_count = self.db_table_count_rows(table)
		if row_count == 0:
			self.demat_summary_insert_data(in_filename)
		else:
			print 'demat_summary data already loaded in db', row_count
		print 'display db data'
		self.demat_summary_load_db()

	def demat_txn_insert_data(self, in_filename):	
		SQL = """insert into demat_txn (stock_symbol, company_name, isin_code, action, quantity, txn_price, brokerage, txn_charges, stamp_duty, segment, stt, remarks, txn_date, exchange, unused1) values (:stock_symbol, :company_name, :isin_code, :action, :quantity, :txn_price, :brokerage, :txn_charges, :stamp_dty, :segment, :stt, :remarks, :txn_date, :exchange, :unused1) """
		cursor = self.db_conn.cursor()
		with open(in_filename, 'rt') as csvfile:
			# future 
			csv_reader = csv.reader(csvfile)
			# insert row
			cursor.executemany(SQL, csv_reader)
			# commit db changes
			self.db_conn.commit()


	def demat_summary_insert_data(self, in_filename):	
		SQL = """insert into demat_summary (stock_symbol, company_name, isin_code, qty, acp, cmp, pct_change, value_cost, value_market, realized_pl, unrealized_pl, unrealized_pl_pct, unused1) values (:stock_symbol, :company_name, :isin_code, :qty, :acp, :cmp, :pct_change, :value_cost, :value_market, :realized_pl, :unrealized_pl, :unrealized_pl_pct, :unused1) """
		cursor = self.db_conn.cursor()
		with open(in_filename, 'rt') as csvfile:
			# future 
			csv_reader = csv.reader(csvfile)
			# insert row
			cursor.executemany(SQL, csv_reader)
			# commit db changes
			self.db_conn.commit()

	def demat_txn_load_db(self):
		table = "demat_txn"
		cursor = self.db_table_load(table)
		for row in cursor.fetchall():
			if self.debug_level > 1 :
				print row
			self.demat_txn_load_row(row)
		# self.demat_txn_prepare_data()


	def demat_summary_load_db(self):
		table = "demat_summary"
		cursor = self.db_table_load(table)
		for row in cursor.fetchall():
			if self.debug_level > 1 :
				print row
			self.demat_summary_load_row(row)
		# self.prepare_demat_data()


	def print_phase1(self, out_filename):
		fh = open(out_filename, "w") 
		fh.write('isin_code, comp_name, action, qty, price, txn_date\n')
		for isin_code in sorted(self.demat_txn_list):
			if self.debug_level > 1:
				print 'dumping isin', isin_code
			fh.write(self.demat_txn_list[isin_code])
		fh.close()

	def print_phase2(self, out_filename):
		fh = open(out_filename, "w") 
		fh.write('isin_code, comp_name, buy_qty, sale_qty, buy_price, sale_price, demat_txn_last_type, demat_txn_last_date\n')
		for isin_code in sorted(self.demat_txn_list):
			if isin_code == 'Stock Symbol':
				continue
			p_str = isin_code
			p_str += ','
			p_str += self.company_name[isin_code] 
			p_str += ','
			p_str += str(self.demat_txn_buy_qty[isin_code])
			p_str += ','
			if isin_code in self.demat_txn_sale_qty:
				p_str += str(self.demat_txn_sale_qty[isin_code])
			else:
				p_str += '0' 
			p_str += ','
			p_str += str(self.demat_txn_buy_price[isin_code])
			p_str += ','
			if isin_code in self.demat_txn_sale_price:
				p_str += str(self.demat_txn_sale_price[isin_code])
			else:
				p_str += '0' 
			p_str += ','
			p_str += self.demat_txn_last_type[isin_code] 
			p_str += ','
			p_str += self.demat_txn_last_date[isin_code] 
			p_str += '\n'
			fh.write(p_str)
		fh.close()

	def print_phase3(self, out_filename, positive_holdings = None):
		fh = open(out_filename,"w") 
		fh.write('isin_code, comp_name, demat_summary_qty, demat_summary_acp, demat_summary_hold_units_1k, demat_txn_last_type, demat_txn_last_date\n')
		for isin_code in sorted(self.demat_txn_list):
			if isin_code == 'Stock Symbol':
				continue
			p_str = isin_code
			p_str += ','
			p_str += self.company_name[isin_code] 
			p_str += ','
			p_str += str(self.demat_summary_qty[isin_code])
			p_str += ','
			p_str += str(self.demat_summary_acp[isin_code])
			p_str += ','
			p_str += str(self.demat_summary_hold_units[isin_code])
			p_str += ','
			p_str += self.demat_txn_last_type[isin_code] 
			p_str += ','
			p_str += self.demat_txn_last_date[isin_code] 
			p_str += '\n'
			if positive_holdings:
				if self.demat_summary_qty[isin_code] > 0:
					fh.write(p_str)
			else:
				fh.write(p_str)
		fh.close()

	def print_phase4(self, out_filename):
		self.print_phase3(out_filename, True)

	def demat_summary_get_upl_pct_by_isin_code(self, isin_code):
		if isin_code in self.demat_summary_upl_pct:
			return self.demat_summary_upl_pct[isin_code]
		return 0

	def demat_summary_get_acp_by_isin_code(self, isin_code):
		if isin_code in self.demat_summary_acp:
			return self.demat_summary_acp[isin_code]
		return 0

	def get_demat_units_by_isin_code(self, isin_code):
		if isin_code in self.demat_summary_hold_units:
			return self.demat_summary_hold_units[isin_code]
		return 0

	def get_demat_txn_last_date_by_isin_code(self, isin_code):
		if isin_code in self.demat_txn_last_date:
			return self.demat_txn_last_date[isin_code]
		return '' 

	def get_demat_txn_last_type_by_isin_code(self, isin_code):
		if isin_code in self.demat_txn_last_type:
			return self.demat_txn_last_type[isin_code]
		return '' 