#!/usr/bin/python

import sys
import re
import csv
import traceback
import operator

import cutil.cutil

class DemSum(object):

	def __init__(self):
		super(DemSum, self).__init__()
		self.company_name = {}
		self.hold_qty = {}
		self.hold_acp = {}
		self.hold_cmp = {}
		self.hold_units	= {}
		self.phase1_data = {}
		self.debug_level = 0 
		print 'init : DemSum'

	def set_debug_level(self, debug_level):
		self.debug_level = debug_level 
		
	def load_demsum_row(self, row, broker_name):
		try:
			row_list = row

			if self.debug_level > 1:
				print 'processing record ', row_list

			if broker_name == 'icicidirect':
				isin_code   = (row_list[2]).upper().strip()
				comp_name = row_list[1]
				hold_qty = row_list[3]
				hold_acp = row_list[4]
				hold_cmp = row_list[5]
			else:
				# zerodha : both isin_code and comp_name
                                # are same as isin code is not included
				isin_code   = row_list[0]
				comp_name = row_list[0]
				hold_qty = row_list[1]
				hold_acp = row_list[2]
				hold_cmp = row_list[3]

			if isin_code == 'ISIN Code': 
				return	
			if isin_code == 'Instrument': 
				return	

			comp_name = cutil.cutil.normalize_comp_name(comp_name)
			comp_name = comp_name.upper()
			if re.search('ETF', comp_name):
				if self.debug_level > 0:
					print 'skipped etf ', row
				return	


			# total : avergae cost price
			hold_acp = str(int(round(float(hold_acp))))

			# total : current market price
			hold_cmp = str(int(round(float(hold_cmp))))

			hold_units = int(round(float(hold_acp)/1000))

			self.company_name[isin_code] = comp_name
			self.hold_qty[isin_code] = hold_qty
			self.hold_acp[isin_code] = hold_acp
			self.hold_cmp[isin_code] = hold_cmp
			self.hold_units[isin_code] = hold_units

			p_str = isin_code 
			p_str += ','
			p_str += comp_name 
			p_str += ','
			p_str += hold_qty
			p_str += ','
			p_str += hold_acp
			p_str += ','
			p_str += hold_cmp
			p_str += '\n'
	
			if isin_code in self.phase1_data:	
				if self.debug_level > 0:
					print 'duplicate record for ISIN ', isin_code	
			else:
				self.phase1_data[isin_code] = p_str
				if self.debug_level > 1:
					print 'stored data for ISIN ', isin_code
				
		except:
			print "Unexpected error:", sys.exc_info()

	def load_demsum_data(self, in_file, broker_name):
		with open(in_file, 'r') as csvfile:
			reader = csv.reader(csvfile)
			for row in reader:
				self.load_demsum_row(row, broker_name)

	def print_phase1(self, out_filename, comp_name_only = False):
		fh = open(out_filename,"w") 
		if comp_name_only == False:
			fh.write('isin_code, comp_name, hold_qty, hold_acp, hold_units_1k\n')
		for isin_code in sorted(self.company_name, key=self.company_name.__getitem__):
			if isin_code == 'Stock Symbol':
				continue
			if comp_name_only:
				p_str = self.company_name[isin_code] 
				p_str += '\n'
			else:
				p_str = isin_code
				p_str += ','
				p_str += self.company_name[isin_code] 
				p_str += ','
				p_str += str(self.hold_qty[isin_code])
				p_str += ','
				p_str += str(self.hold_acp[isin_code])
				p_str += ','
				p_str += str(self.hold_units[isin_code])
				p_str += '\n'
			fh.write(p_str)
		fh.close()
	def print_phase2(self, out_filename):
		self.print_phase1(out_filename, True)
