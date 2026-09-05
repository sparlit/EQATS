#!/usr/bin/python

import sys
import re
import csv
import traceback

import cutil.cutil

from amfi.amfi import * 

class Plan(Amfi):

	def __init__(self):
		super(Plan, self).__init__()
		# years of investing. started in 2017
		self.plan_multiply = self.INVEST_YEARS
		self.plan_comp_units = {}
		self.plan_indu_units = {}
		self.debug_level = 0 
		self.last_row = "" 
		print 'init : Plan'

	def set_debug_level(self, debug_level):
 		self.debug_level = debug_level

	def load_plan_row(self, row):
		try:
			row_list = row
		
			if row_list[0] == 'comp_industry':
				return
			comp_industry = row_list[0]
			comp_name = row_list[1]
			comp_ticker = row_list[2]
			comp_weight = row_list[3]
			comp_desc = row_list[4]
			if comp_industry in self.plan_indu_units.keys():
				self.plan_indu_units[comp_industry] = self.plan_indu_units[comp_industry] + comp_weight
			else:
				self.plan_indu_units[comp_industry] = comp_weight
			if self.debug_level > 0:
				print 'industry ', comp_industry 
				print 'company name', comp_name 
				print 'company weight', comp_weight
				print 'company desc', comp_desc
			# use ticker as an input
			isin = self.get_amfi_isin_by_name(comp_ticker)
			if self.debug_level > 0:
				print isin, comp_name
			if comp_weight >= 0:
				self.plan_comp_units[isin] = cutil.cutil.get_number(comp_weight)
				self.plan_comp_units[isin] = self.plan_comp_units[isin] * self.plan_multiply
			else:
				self.plan_comp_units[isin] = 0
			return
		except TypeError:
			print 'except : TypeError : ' , row  , "\n"
		except IndexError:
			print 'except : IndexError : ' , row , "\n"
			traceback.print_exc()

	def load_plan_data(self, in_filename):
		table = "plan"
		row_count = self.db_table_count_rows(table)
		if row_count == 0:
			self.insert_plan_data(in_filename)
		else:
			print 'plan data already loaded in db', row_count
		print 'display db data'
		self.load_plan_db()
		
	def insert_plan_data(self, in_filename):	
		SQL = """insert into plan(comp_industry, comp_name, comp_ticker, comp_weight, comp_desc) values (:comp_industry, :comp_name, :comp_ticker, :comp_weight, :comp_desc) """
		cursor = self.db_conn.cursor()
		with open(in_filename, 'rt') as csvfile:
			# future 
			csv_reader = csv.reader(csvfile)
			# insert row
			cursor.executemany(SQL, csv_reader)
			# commit db changes
			self.db_conn.commit()

	def load_plan_db(self):
		table = "plan"
		cursor = self.db_table_load(table)
		for row in cursor.fetchall():
			if self.debug_level > 1 :
				print row
			self.load_plan_row(row)

	def plan_dump_ticker(self, out_filename):
		lines = []
		fh = open(out_filename, "w") 
		sorted_items = sorted(self.plan_comp_units, key=self.plan_comp_units.__getitem__, reverse=True)

		for isin in sorted_items: 
			try:
			        comp_name = self.get_amfi_cname_by_code(isin)
				if self.debug_level >= 2:
					print comp_name
				if isin in self.plan_comp_units:
					units_1k = int(self.plan_comp_units[isin])
				else:
					units_1k = 0
				if units_1k > 0: 
					p_str = self.get_amfi_ticker_by_code(isin) 
					# p_str += ' '
					# p_str += comp_name
					p_str += '\n'
					lines.append(p_str)
			except ValueError:
				print 'except : ValueError :', comp_name
		lines.sort()
		fh.writelines(lines)
		return

	def plan_dump_generic(self, out_filename, sort_type_rank = None, plus_holdings = None, zero_holdings = None):
		total_units = 0
		cap_units = {}
		fh = open(out_filename, "w") 
		fh.write('comp_name, ticker, isin, plan_units_1k, rank, captype, mcap\n')
		if sort_type_rank:
			sorted_items = sorted(self.amfi_rank, key=self.amfi_rank.__getitem__)
			if self.debug_level > 2:
				print sorted_items
		else:
			sorted_items = sorted(self.plan_comp_units, key=self.plan_comp_units.__getitem__, reverse=True)

		for isin in sorted_items: 
			try:
				# isin = self.get_amfi_isin_by_name(comp_name)
			        comp_name = self.get_amfi_cname_by_code(isin)
				if self.debug_level >= 2:
					print comp_name
				if isin in self.plan_comp_units:
					units_1k = int(self.plan_comp_units[isin])
				else:
					units_1k = 0
				if self.debug_level >= 2:
					print units_1k 
				mcap = self.get_amfi_mcap_by_code(isin)
				captype = self.get_amfi_captype_by_code(isin)
				if self.debug_level > 0:
					print isin, captype 
				rank = self.get_amfi_rank_by_code(isin)
				ticker = self.get_amfi_ticker_by_code(isin)
				total_units += units_1k
				if captype in cap_units:
					cap_units[captype] += units_1k
				else:
					cap_units[captype] = units_1k
			except ValueError:
				print 'except : ValueError :', comp_name

			if plus_holdings:
				if units_1k <= 0 :
					continue

			if zero_holdings :
				if units_1k > 0 :
					continue

			if sort_type_rank:
				if  rank > 500 and units_1k <= 0:
					continue

			p_str = comp_name
			p_str += ', '
			p_str += ticker 
			p_str += ', '
			p_str += isin 
			p_str += ', '
			if isin in self.plan_comp_units:
				p_str += str(self.plan_comp_units[isin])
			else:
				p_str += '0'
			p_str += ', '
			p_str += str(rank)
			p_str += ', '
			p_str += captype 
			p_str += ', '
			p_str += str(mcap)
			p_str += '\n'
			fh.write(p_str)
		if self.debug_level > 0 :
			print cap_units 
		# Current portfolio distribution 
		p_str = 'Summary'
		p_str += ', '
		p_str += '-' 
		p_str += ', '
		p_str += '-' 
		p_str += ', '
		p_str += str(total_units)
		p_str += ', '
		try:
			p_str += 'large '  + str(int(round(float((cap_units['Large Cap']*100.0)/total_units)))) +' %'
			p_str += ', '
			p_str += 'mid '  + str(int(round(float((cap_units['Mid Cap']*100.0)/total_units)))) + ' %'
			p_str += ', '
			p_str += 'small '  + str(int(round(float(((cap_units['Small Cap']+cap_units['Micro Cap']+cap_units['Nano Cap']+cap_units['Unknown Cap'])*100.0)/total_units)))) + ' %'
			p_str += '\n'
		except KeyError:
			print 'except KeyError'
			traceback.print_exc()
				
		fh.write(p_str)
		
		# Ideal portfolio distribution 
		p_str = 'Ideal'
		p_str += ', '
		p_str += '-' 
		p_str += ', '
		p_str += '-' 
		p_str += ', '
		p_str += '100'
		p_str += ', '
		p_str += 'large '  + '65-70' +' %'
		p_str += ', '
		p_str += 'mid '  + '20' + ' %'
		p_str += ', '
		p_str += 'small '  + '10-15' + ' %'
		p_str += '\n'
		fh.write(p_str)
		fh.close()

	# print all holdings : plus and zero 
	def plan_dump_sorted_units(self, out_filename):
		self.plan_dump_generic(out_filename, sort_type_rank=False)

	# print all holdings : plus and zero 
	def plan_dump_all(self, out_filename):
		self.plan_dump_generic(out_filename, sort_type_rank=True)

	# print plus holdings only
	def plan_dump_plus(self, out_filename):
		self.plan_dump_generic(out_filename, sort_type_rank=True, plus_holdings=True)

	# print zero holdings only
	def plan_dump_zero(self, out_filename):
		self.plan_dump_generic(out_filename, sort_type_rank=True, zero_holdings=True)

	def get_plan_comp_units(self, name):
		if name in self.plan_comp_units:
			return self.plan_comp_units[name]	
		else:
			print 'invalid key :', name

	def print_comp_data(self):
		print self.plan_comp_units

	def size_comp_data(self):
		print len(self.plan_comp_units)

	def get_plan_indu_units(self, name):
		if name in self.plan_indu_units:
			return self.plan_indu_units[name]	
		else:
			print 'invalid key :', name

	def print_indu_data(self):
		print self.plan_indu_units

	def size_indu_data(self):
		print len(self.plan_indu_units)

