#!/usr/bin/python

import sys
import re
import csv
import traceback
import operator
import cutil.cutil
import finratio.comp_perf
import finratio.comp_price

from isin.isin import *
from amfi.amfi import * 

#class Screener(Isin):
class Screener(Isin, Amfi):
	def __init__(self):
		super(Screener, self).__init__()
		self.sc_sno = [] 
		self.sc_name = {} 
		self.sc_cmp = {}
		self.sc_myavgiv = {}
		self.sc_iv = {}
		self.sc_mcap = {}
		self.sc_sales = {}
		self.sc_np = {}
		self.sc_pe = {}
		self.sc_pe5 = {}
		self.sc_eps = {}
		self.sc_peg = {}
		self.sc_p2bv = {}
		self.sc_p2ocf = {}
		self.sc_p2sales = {}
		self.sc_ev2ebitda = {}
		self.sc_ev = {}
		self.sc_opm = {}
		self.sc_d2e = {}
		self.sc_ic = {}
		self.sc_dp = {}
		self.sc_dp3 = {}
		self.sc_dy = {}
		self.sc_roe3 = {}
		self.sc_roce3 = {}
		self.sc_cr = {}
		self.sc_sales5 = {}
		self.sc_profit5 = {}
		self.sc_pledge = {}
		self.sc_promhold = {}
		self.sc_piotski = {}
		self.sc_altmanz = {}
		self.sc_graham = {}
		self.sc_crank = {}
		self.sc_prank = {}
                self.sc_name_aliases = {}
		# margin of safety
		self.sc_mos = {}
 		self.debug_level = 0 
		self.sc_ratio_name = { 'S.No. ':'sno','Name ':'name','CMP Rs. ':'cmp','MyAvgIV ':'myavgiv','IV Rs. ':'iv','Mar Cap Rs.Cr. ':'mcap','Sales Rs.Cr. ':'sales','NP 12M Rs.Cr. ':'np','P/E ':'pe','5Yrs PE ':'pe5','EPS 12M Rs. ':'eps','PEG ':'peg','CMP / BV ':'p2bv','CMP / OCF ':'p2ocf','CMP / Sales ':'p2sales','EV / EBITDA ':'ev2ebitda', 'EV Rs.Cr. ' : 'ev' , 'OPM % ':'opm','Debt / Eq ':'d2e','Int Coverage ':'ic','Dividend Payout % ':'dp','Avg Div Payout 3Yrs % ':'dp3','Div Yld % ':'dy','ROE 3Yr % ':'roe3','ROCE3yr avg % ':'roce3','Current ratio ':'cr','Sales Var 5Yrs % ':'sales5','Profit Var 5Yrs % ':'profit5','Pledged % ':'pledge','Prom. Hold. % ':'prom_hold','Piotski Scr ':'piotski' }
		self.sc_ratio_loc = { 'sno' : 0,'name' : 0,'cmp' : 0,'myavgiv' : 0,'iv' : 0,'mcap' : 0,'sales' : 0,'np' : 0,'pe' : 0,'pe5' : 0,'eps' : 0,'peg' : 0,'p2bv' : 0,'p2ocf' : 0,'p2sales' : 0,'ev2ebitda' : 0,'ev' : 0,'opm' : 0,'d2e' : 0,'icover' : 0,'dp' : 0,'dp3' : 0,'dy' : 0,'roe3' : 0,'roce3' : 0,'cr' : 0,'sales5' : 0,'profit5' : 0,'pledge' : 0,'prom_hold' : 0,'piotski' : 0 }

	def set_debug_level(self, debug_level):
 		self.debug_level = debug_level

	def load_screener_name_aliases(self, sc_aliases_filename):
		with open(sc_aliases_filename, 'r') as csvfile:
			reader = csv.reader(csvfile)
			for row in reader:
				sc_name, isin_name = row
				sc_name = sc_name.strip().capitalize()
				isin_name = isin_name.strip().capitalize()
				if self.debug_level > 1: 
					print 'alias ', sc_name
					print 'real ',isin_name 
				self.sc_name_aliases[sc_name] = isin_name 
		print self.sc_name_aliases

	def resolve_screener_name_alias(self, company_name):
		sc_name = company_name.strip().capitalize()
		if sc_name in self.sc_name_aliases.keys():
			company_name = self.sc_name_aliases[sc_name]
		return company_name

	def load_screener_row(self, row):
		try:
			row_list = row
			if len(row_list) == 0:
				if self.debug_level > 1:
					print 'ignored empty row', row_list
				return

			sc_no = row_list[0].strip()
			if sc_no == 'S.No.': 
				if self.debug_level > 1:
					print 'picked up keys', row_list
				rindex = 0
				for ratio in row_list:
					if ratio in self.sc_ratio_name.keys():
						if self.debug_level > 1:
							print 'found ', ratio
						self.sc_ratio_loc[self.sc_ratio_name[ratio]] = rindex
						rindex += 1
					else:
						print 'check sc_ratio_name for', ratio
				return

			sc_sno = cutil.cutil.get_number(row_list[self.sc_ratio_loc['sno']])
			sc_name = row_list[self.sc_ratio_loc['name']]
			screener_name = sc_name
			sc_name = self.resolve_screener_name_alias(sc_name)
			sc_name = cutil.cutil.normalize_comp_name(sc_name)
			# isin_code = self.get_isin_code_by_name(sc_name)
			isin_code = self.get_amfi_isin_by_name(sc_name)
			if isin_code == '':
				print 'screener: unable to get isin_code :', screener_name, ': ', sc_name 
			else:
				sc_sno = isin_code
				if self.debug_level > 1:
					print 'Found isin_code : ', sc_sno, ' for ', sc_name
			sc_cmp = cutil.cutil.get_number(row_list[self.sc_ratio_loc['cmp']])
			sc_myavgiv = cutil.cutil.get_number(row_list[self.sc_ratio_loc['myavgiv']])
			sc_iv  = cutil.cutil.get_number(row_list[self.sc_ratio_loc['iv']]) 
			sc_mcap  = cutil.cutil.get_number(row_list[self.sc_ratio_loc['mcap']]) 
			sc_sales  = cutil.cutil.get_number(row_list[self.sc_ratio_loc['sales']]) 
			sc_np = cutil.cutil.get_number(row_list[self.sc_ratio_loc['np']]) 
			sc_pe = cutil.cutil.get_number(row_list[self.sc_ratio_loc['pe']]) 
			sc_pe5 = cutil.cutil.get_number(row_list[self.sc_ratio_loc['pe5']]) 
			sc_eps = cutil.cutil.get_number(row_list[self.sc_ratio_loc['eps']]) 
			sc_peg = cutil.cutil.get_number(row_list[self.sc_ratio_loc['peg']]) 
			sc_opm = cutil.cutil.get_number(row_list[self.sc_ratio_loc['opm']]) 
			sc_dp = cutil.cutil.get_number(row_list[self.sc_ratio_loc['dp']]) 
			sc_d2e = cutil.cutil.get_number(row_list[self.sc_ratio_loc['d2e']]) 
			sc_ic = cutil.cutil.get_number(row_list[self.sc_ratio_loc['ic']]) 
			sc_dy = cutil.cutil.get_number(row_list[self.sc_ratio_loc['dy']]) 
			sc_p2bv = cutil.cutil.get_number(row_list[self.sc_ratio_loc['p2bv']]) 
			sc_dp3 = cutil.cutil.get_number(row_list[self.sc_ratio_loc['dp3']]) 
			sc_ev = cutil.cutil.get_number(row_list[self.sc_ratio_loc['ev']]) 
			# TBD GOLD sc_altmanz = cutil.cutil.get_number(row_list[self.sc_ratio_loc['altmanz']]) 
			sc_altmanz = 0 
			sc_cr = cutil.cutil.get_number(row_list[self.sc_ratio_loc['cr']]) 
			sc_roe3 = cutil.cutil.get_number(row_list[self.sc_ratio_loc['roe3']]) 
			sc_roce3 = cutil.cutil.get_number(row_list[self.sc_ratio_loc['roce3']]) 
			# TBD GOLD sc_graham = cutil.cutil.get_number(row_list[self.sc_ratio_loc['graham']]) 
			sc_graham = 0 
			sc_sales5 = cutil.cutil.get_number(row_list[self.sc_ratio_loc['sales5']]) 
			sc_profit5 = cutil.cutil.get_number(row_list[self.sc_ratio_loc['profit5']]) 
			sc_ev2ebitda = cutil.cutil.get_number(row_list[self.sc_ratio_loc['ev2ebitda']]) 
			sc_pledge = cutil.cutil.get_number(row_list[self.sc_ratio_loc['pledge']]) 

			self.sc_sno.append(sc_sno)

			self.sc_name[sc_sno] = sc_name
			self.sc_cmp[sc_sno] = sc_cmp
			self.sc_sales[sc_sno] = sc_sales
			self.sc_np[sc_sno] = sc_np 
			self.sc_pe[sc_sno] =  sc_pe
			self.sc_opm[sc_sno] = sc_opm 
			self.sc_eps[sc_sno] =  sc_eps
			self.sc_dp[sc_sno] =  sc_dp
			self.sc_d2e[sc_sno] = sc_d2e 
			self.sc_ic[sc_sno] = sc_ic 
			self.sc_dy[sc_sno] = sc_dy 
			self.sc_peg[sc_sno]  = sc_peg
			self.sc_p2bv[sc_sno]  = sc_p2bv 
			self.sc_dp3[sc_sno]  = sc_dp3 
			self.sc_myavgiv[sc_sno]  = sc_myavgiv 
			self.sc_iv[sc_sno]  = sc_iv 
			self.sc_ev[sc_sno]  = sc_ev 
			self.sc_mcap[sc_sno]  = sc_mcap 
			self.sc_altmanz[sc_sno] = sc_altmanz
			self.sc_cr[sc_sno] = sc_cr 
			self.sc_roe3[sc_sno] = sc_roe3 
			self.sc_roce3[sc_sno] = sc_roce3 
			self.sc_graham[sc_sno] = sc_graham 
			self.sc_sales5[sc_sno] = sc_sales5
			self.sc_profit5[sc_sno] = sc_profit5 
			self.sc_ev2ebitda[sc_sno] =  sc_ev2ebitda
			self.sc_pledge[sc_sno] =  sc_pledge
			# margin of safety
			# cmp(40), iv(80) - upside 100%
			# cmp(80), iv(40) - downside 50%
			if sc_myavgiv > 0:
				self.sc_mos[sc_sno] = int(float(sc_myavgiv-sc_cmp)*100.0/float(sc_cmp))
			else:
				self.sc_mos[sc_sno] = 0
			
			sc_crank = 0
			
			sc_crank += finratio.comp_perf.get_cscore_opm(sc_opm)
			sc_crank += finratio.comp_perf.get_cscore_dp(sc_dp)
			sc_crank += finratio.comp_perf.get_cscore_d2e(sc_d2e)
			sc_crank += finratio.comp_perf.get_cscore_ic(sc_ic)
			sc_crank += finratio.comp_perf.get_cscore_dp(sc_dp3)
			sc_crank += finratio.comp_perf.get_cscore_current_ratio(sc_cr)
			sc_crank += finratio.comp_perf.get_cscore_pledge(sc_pledge)
			sc_crank += finratio.comp_perf.get_cscore_altmanz(sc_altmanz)
			if sc_np > 0:
				sc_crank += 1
			if sc_eps > 0:
				sc_crank += 1
			if sc_roe3 > 6:
				sc_crank += 1 
			
			sc_prank = 0
			sc_prank += finratio.comp_price.get_pscore_pe(sc_pe)
			sc_prank += finratio.comp_price.get_pscore_peg(sc_peg)
			sc_prank += finratio.comp_price.get_pscore_pb(sc_p2bv)
			sc_prank += finratio.comp_price.get_pscore_dy(sc_dy)
			sc_prank += finratio.comp_price.get_pscore_iv(sc_cmp, sc_iv)
			sc_prank += finratio.comp_price.get_pscore_graham(sc_cmp, sc_graham)
		
			self.sc_crank[sc_sno] = sc_crank
			self.sc_prank[sc_sno] = sc_prank
			
			if self.debug_level > 1:
				print 'score : ', str(sc_sno) , ', ', sc_name , str(sc_crank) , '\n'
			
		except IndexError:
			print 'except ', row
			traceback.print_exc()
		except KeyError:
			print 'except ', row
			traceback.print_exc()
		except:
			print 'except ', row
			traceback.print_exc()
		
	def load_isin_data_both(self, isin_bse_filename, isin_nse_filename):
		# self.load_isin_bse_data(isin_bse_filename)
		# self.load_isin_nse_data(isin_nse_filename)
		self.load_isin_db()

	def load_screener_data(self, sc_filename):
		with open(sc_filename, 'r') as csvfile:
			reader = csv.reader(csvfile)
			for row in reader:
				self.load_screener_row(row)

	def print_phase1(self, out_filename, sort_score = None):
		fh = open(out_filename, "w") 
		fh.write('sc_isin, sc_name, sc_cmp, sc_sales, sc_np, sc_pe, sc_opm, sc_eps, sc_dp3, sc_d2e, sc_ic, sc_dy, sc_peg, sc_p2bv, sc_dp3, sc_iv, sc_ev, sc_mcap, sc_altmanz, sc_cr, sc_roe3, sc_roce3, sc_graham, sc_sales5, sc_profit5, sc_ev2ebitda, sc_pledge, sc_mos, sc_crank, sc_prank\n')
		if sort_score:
			sorted_input = sorted(self.sc_crank, key=self.sc_crank.__getitem__, reverse=True)
		else:
			sorted_input = sorted(self.sc_sno)

		for sc_sno in sorted_input:
			p_str = str(sc_sno)
			p_str += ', ' 
			p_str += self.sc_name[sc_sno]
			p_str += ', ' 
			if sc_sno in self.sc_cmp:
				p_str += str(self.sc_cmp[sc_sno])
			else:
				p_str += '-'
			p_str += ', ' 
			p_str += str(self.sc_sales[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_np[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_pe[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_opm[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_eps[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_dp[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_d2e[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_ic[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_dy[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_peg[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_p2bv[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_dp3[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_iv[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_ev[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_mcap[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_altmanz[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_cr[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_roe3[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_roce3[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_graham[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_sales5[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_profit5[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_ev2ebitda[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_pledge[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_mos[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_crank[sc_sno])
			p_str += ', ' 
			p_str += str(self.sc_prank[sc_sno])
			p_str += '\n' 
			fh.write(p_str);	
		fh.close()

	def print_phase2(self, out_filename):
		self.print_phase1(out_filename, True)

	def get_sc_sno_by_name(self, req_name):
		for sc_sno in sorted(self.sc_sno):
			sc_name = self.sc_name[sc_sno]
			# try to find a matching company
			if re.match(sc_name.strip(), req_name.strip()):
				if self.debug_level > 1:
					print 'sc: screener found match : ', req_name, ', sc_sno : ', sc_sno 
				return sc_sno
		return 0

	def get_sc_crank_by_sno(self, sc_sno):
		if sc_sno in self.sc_crank:
			return self.sc_crank[sc_sno]
		return 0

	def get_sc_prank_by_sno(self, sc_sno):
		if sc_sno in self.sc_prank:
			return self.sc_prank[sc_sno]
		return 0

	def get_sc_cmp_by_sno(self, sc_sno):
		if sc_sno in self.sc_cmp:
			return self.sc_cmp[sc_sno]
		return 0
	def get_sc_iv_by_sno(self, sc_sno):
		if sc_sno in self.sc_iv:
			return self.sc_iv[sc_sno]
		return 0

	def get_sc_dp3_by_sno(self, sc_sno):
		if sc_sno in self.sc_dp3:
			return self.sc_dp3[sc_sno]
		return 0

	def get_sc_dp_by_sno(self, sc_sno):
		if sc_sno in self.sc_dp:
			return self.sc_dp[sc_sno]
		return 0

	def get_sc_dy_by_sno(self, sc_sno):
		if sc_sno in self.sc_dy:
			return self.sc_dy[sc_sno]
		return 0

	def get_sc_myavgiv_by_sno(self, sc_sno):
		if sc_sno in self.sc_myavgiv:
			return self.sc_myavgiv[sc_sno]
		return 0

	def get_sc_d2e_by_sno(self, sc_sno):
		if sc_sno in self.sc_d2e:
			return self.sc_d2e[sc_sno]
		return 0

	def get_sc_roe3_by_sno(self, sc_sno):
		if sc_sno in self.sc_roe3:
			return self.sc_roe3[sc_sno]
		return 0

	def get_sc_roce3_by_sno(self, sc_sno):
		if sc_sno in self.sc_roce3:
			return self.sc_roce3[sc_sno]
		return 0

	def get_sc_sales5_by_sno(self, sc_sno):
		if sc_sno in self.sc_sales5:
			return self.sc_sales5[sc_sno]
		return 0

	def get_sc_profit5_by_sno(self, sc_sno):
		if sc_sno in self.sc_profit5:
			return self.sc_profit5[sc_sno]
		return 0

	def get_sc_mos_by_sno(self, sc_sno):
		if sc_sno in self.sc_mos:
			return self.sc_mos[sc_sno]
		return 0

	def get_sc_peg_by_sno(self, sc_sno):
		if sc_sno in self.sc_peg:
			return self.sc_peg[sc_sno]
		return 0

	def get_sc_pledge_by_sno(self, sc_sno):
		if sc_sno in self.sc_pledge:
			return self.sc_pledge[sc_sno]
		return 0


	def get_sc_graham_by_sno(self, sc_sno):
		if sc_sno in self.sc_graham:
			return self.sc_graham[sc_sno]
		return 0
