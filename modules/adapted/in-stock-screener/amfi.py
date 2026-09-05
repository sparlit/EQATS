#!/usr/bin/python

import sys
import re
import csv
import traceback
import operator

import sqlite3

import cutil.cutil

from database.database import *

class Amfi(Database):
	def __init__(self):
		super(Amfi, self).__init__()
		# isin number
		self.amfi_isin = [] 
		# serial number
		self.amfi_rank = {}
		self.amfi_cname = {}
		self.amfi_ticker = {}
		self.amfi_mcap = {}
		self.amfi_captype = {}
 		self.debug_level = 0 

	def set_debug_level(self, debug_level):
 		self.debug_level = debug_level

	def load_amfi_row(self, row):
		try:
			row_list = row
			if len(row_list) == 0:
				print 'ignored empty row', row_list
				return
			
			serial_number = row_list[0]
			if serial_number == 'Sr. No.':
				if self.debug_level > 0:
					print 'skipped header line', row_list
				return
			
			serial_number = cutil.cutil.get_number(serial_number)
			
			comp_name = row_list[1]
			isin_number = row_list[2]
			comp_ticker = row_list[3].upper().strip()
			if comp_ticker == '':
				comp_ticker = row_list[5]
			avg_mcap = cutil.cutil.get_number(row_list[9])
			captype = row_list[10].strip()
			if captype == 'Small Cap':
				if serial_number > 500 and serial_number < 750:
					captype = 'Micro Cap'
				if serial_number > 750 and serial_number < 1000:
					captype = 'Nano Cap'
				if serial_number > 1000:
					captype = 'Unknown Cap'
			
			comp_name = cutil.cutil.normalize_comp_name(comp_name)
			
			if self.debug_level > 1:
				print 'serial_number : ', serial_number	
				print 'isin_number: ', isin_number
				print 'comp_ticker : ', comp_ticker
				print 'avg_mcap : ', avg_mcap 
				print 'captype : ', captype 
				print 'comp_name : ', comp_name
			
			self.amfi_rank[isin_number] = serial_number
			self.amfi_cname[isin_number] = comp_name 
			self.amfi_ticker[isin_number] = comp_ticker 
			self.amfi_mcap[isin_number] = avg_mcap 
			self.amfi_captype[isin_number] = captype 
			self.amfi_isin.append(isin_number)
			
			if self.debug_level > 1:
				print 'comp_name : ', comp_name , '\n'
				print 'isin_number: ', isin_number, '\n'
			
		except IndexError:
			print 'except ', row
		except:
			print 'except ', row
			traceback.print_exc()
		
	def load_amfi_data(self, in_filename):
		table = "amfi"
		# row_count = self.count_amfi_db(table)
		row_count = self.db_table_count_rows(table)
		if row_count == 0:
			self.insert_amfi_data(in_filename)
		else:
			print 'amfi data already loaded in db', row_count
		print 'display db data'
		self.load_amfi_db()
		
	def insert_amfi_data(self, in_filename):	
		SQL = """insert into amfi (sno, company_name, isin, bse_symbol, bse_mcap, nse_symbol, nse_mcap, mse_symbol, mse_mcap, avg_mcap, cap_type, unused1, unused2) values (:sno, :company_name, :isin, :bse_symbol, :bse_mcap, :nse_symbol, :nse_mcap, :mse_symbol, :mse_mcap, :avg_mcap, :cap_type, :unused1, :unused2) """
		cursor = self.db_conn.cursor()
		with open(in_filename, 'rt') as csvfile:
			# future 
			csv_reader = csv.reader(csvfile)
			# insert row
			cursor.executemany(SQL, csv_reader)
			# commit db changes
			self.db_conn.commit()

	def load_amfi_db(self):
		table = "amfi"
		cursor = self.db_table_load(table)
		for row in cursor.fetchall():
			if self.debug_level > 1 :
				print row
			self.load_amfi_row(row)

	def print_phase1(self, out_filename):
		if self.debug_level > 0:
			print 'filename ', out_filename
		fh = open(out_filename, "w") 
		fh.write('amfi_rank, amfi_cname, amfi_isin, amfi_ticker, amfi_mcap, amfi_captype\n')
		for amfi_isin in sorted(self.amfi_rank, key=self.amfi_rank.__getitem__):
			if self.debug_level > 1:
				print 'isin ', amfi_isin
			p_str = str(self.amfi_rank[amfi_isin])
			p_str += ', ' 
			p_str += self.amfi_cname[amfi_isin]
			p_str += ', ' 
			p_str += amfi_isin
			p_str += ', ' 
			p_str += self.amfi_ticker[amfi_isin]
			p_str += ', ' 
			p_str += str(self.amfi_mcap[amfi_isin])
			p_str += ', ' 
			p_str += self.amfi_captype[amfi_isin]
			p_str += '\n' 
			fh.write(p_str);	
		fh.close()

	def get_amfi_isin_by_name(self, req_name):
		req_name = re.sub('\s+', ' ', req_name).strip()
		for amfi_isin in sorted(self.amfi_cname):
			# try to find a matching company
			comp_name = self.amfi_cname[amfi_isin]
			comp_name = comp_name.strip()
			if re.match(req_name, comp_name):
				if self.debug_level > 1:
					print 'found match : name : ', req_name
				return amfi_isin
			if amfi_isin in  self.amfi_ticker:
				ticker_symbol = self.amfi_ticker[amfi_isin]
				if req_name.upper() == ticker_symbol :
					if self.debug_level > 1:
						print 'found ticker : ', req_name
					return amfi_isin	
		if self.debug_level > 1:
			print 'amfi : comp not found : req_name :',req_name,':'
		return ''

	def get_amfi_captype_by_code(self, amfi_isin):
		if amfi_isin in self.amfi_captype:
			return self.amfi_captype[amfi_isin]
		return '-'

	def get_amfi_rank_by_code(self, amfi_isin):
		if amfi_isin in self.amfi_rank:
			return self.amfi_rank[amfi_isin]
		return '0'

	def get_amfi_mcap_by_code(self, amfi_isin):
		if amfi_isin in self.amfi_mcap:
			return self.amfi_mcap[amfi_isin]
		return '0'

	def get_amfi_cname_by_code(self, amfi_isin):
		if amfi_isin in self.amfi_cname:
			return self.amfi_cname[amfi_isin]
		return 'UNK_COMP'

	def get_amfi_ticker_by_code(self, amfi_isin):
		if amfi_isin in self.amfi_ticker:
			return self.amfi_ticker[amfi_isin]
		return 'UNK_TICKER'
