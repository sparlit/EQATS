
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

import datetime

from plan.plan import * 
from demat.demat import * 
from isin.isin import * 
from screener.screener import * 

class Tbd(Plan, Demat, Screener):
	def __init__(self):
		super(Tbd, self).__init__()
		# Plan.__init__(debug_level)
		# Demat.__init__(debug_level)
		self.tbd_last_txn_days = {}
		self.tbd_demat_units = {}
		self.tbd_units = {}
		self.tbd_pct = {}
		self.tbd_isin_name = {}
		self.tbd_isin_code = {}
		self.tbd_captype = {}
		self.tbd_crank = {}
		self.tbd_prank = {}
		self.tbd_mos = {}
		self.tbd_demat_last_txn_date = {}
		self.tbd_demat_last_txn_type = {}

	
	def set_debug_level(self, debug_level):
		self.debug_level = debug_level

	def load_tbd_data(self, screener_aliases_filename, screener_filename):
		self.load_isin_db()
		self.demat_txn_load_db()
		self.demat_summary_load_db()
		self.load_amfi_db()
		self.load_plan_db()
		# self.load_isin_data(isin_nse_filename, "nse")
		# self.load_demat_data(demat_filename)
		# self.load_amfi_data(amfi_filename)
		# self.load_plan_data(plan_filename)
		self.load_screener_name_aliases(screener_aliases_filename)
		self.load_screener_data(screener_filename)
		self.process_tbd_data()
	
	def process_tbd_data(self):
		for isin_code in sorted(self.plan_comp_units):
			try:
				plan_units = int(self.plan_comp_units[isin_code])
			        isin_name = self.get_isin_name_by_code(isin_code)
				comp_name = isin_name
				self.tbd_isin_code[comp_name] = isin_code	

				if isin_code == '':
					self.tbd_captype[comp_name] =   '-'
					if self.debug_level > 0:
						print 'not found isin', comp_name
				else:
					captype = self.get_amfi_captype_by_code(isin_code)
					self.tbd_captype[comp_name] =  captype 
				
				demat_units = int(self.get_demat_units_by_isin_code(isin_code)) 
				self.tbd_demat_units[comp_name] = demat_units 
				demat_last_txn_date = self.get_demat_txn_last_date_by_isin_code(isin_code)
				self.tbd_demat_last_txn_date[comp_name] = demat_last_txn_date 
				if demat_last_txn_date != '':
					last_datetime = datetime.datetime.strptime(demat_last_txn_date, '%d-%b-%Y').date()
					my_delta = datetime.datetime.now().date() - last_datetime
					last_txn_days = my_delta.days
				else:
					last_txn_days = 0
				
				self.tbd_last_txn_days[comp_name] = last_txn_days
				
				self.tbd_demat_last_txn_type[comp_name] = self.get_demat_txn_last_type_by_isin_code(isin_code)
				tbd_units = plan_units - demat_units
				if plan_units <= 0:
					tbd_pct = 0
				else:
					tbd_pct = float((100.0*tbd_units)/plan_units)
				tbd_pct = format(tbd_pct, '.2f')
				self.tbd_units[comp_name] = tbd_units
				self.tbd_pct[comp_name] = tbd_pct
			        isin_name = self.get_isin_name_by_code(isin_code)
				if isin_name == '':
					self.tbd_isin_name[comp_name] = comp_name
					sc_crank = 0
					sc_prank = 0
					sc_mos = 0
				else:
					self.tbd_isin_name[comp_name] = isin_name
					sc_crank = self.get_sc_crank_by_sno(isin_code)
					sc_prank = self.get_sc_prank_by_sno(isin_code)
					sc_mos = self.get_sc_mos_by_sno(isin_code)
				self.tbd_crank[comp_name] = sc_crank
				self.tbd_prank[comp_name] = sc_prank
				self.tbd_mos[comp_name] = sc_mos
			except ValueError:
				print 'except : process: ValueError :', comp_name
	
	def print_tbd_phase1(self, out_filename, plan_only = None, tbd_only = None, days_filter = None, apply_cond = True, demat_only = None, sort_sale = None, mos = 10):
		fh = open(out_filename, "w")
		fh.write('comp_name, isin, plan_1k, demat_1k, tbd_1k, tbd_pct, last_txn_date, days, type, captype, sc_cmp, sc_myavgiv, upside, upl, acp, sc_dp3, sc_d2e, sc_roe3, sc_roce3, sc_sales5, sc_profit5, sc_peg, sc_pledge, comments\n')
		# for comp_name in sorted(self.tbd_last_txn_days, key=self.tbd_last_txn_days.__getitem__, reverse=True):
		if sort_sale:
			# earlier tbd_crank
			sorted_items = sorted(self.tbd_mos, key=self.tbd_mos.__getitem__)
		else:
			# earlier tbd_prank
			sorted_items = sorted(self.tbd_mos, key=self.tbd_mos.__getitem__, reverse=True)
		for comp_name in sorted_items:
			try:
			        isin_code = self.get_isin_code_by_name(comp_name)
				if isin_code in self.plan_comp_units:
					plan_units = int(self.plan_comp_units[isin_code])
				else:
					plan_units = 0
				if plan_only and plan_units <= 0:
					if self.debug_level > 1:
						print 'no planned units : ', comp_name
					continue	
				
				isin_code = self.tbd_isin_code[comp_name]
				
				if comp_name in self.tbd_demat_units:
					demat_units = int(self.tbd_demat_units[comp_name])
				else:
					demat_units = 0

				if demat_only and demat_units <= 0:
					continue
					
				tbd_units = int(self.tbd_units[comp_name])
				tbd_pct = int(round(float(self.tbd_pct[comp_name])))
				sc_crank = self.tbd_crank[comp_name] 
				sc_prank = self.tbd_prank[comp_name] 
				sc_mos = self.tbd_mos[comp_name] 
				if isin_code == '':
					sc_cmp = 0
					sc_iv = 0
					sc_myavgiv = 0
					upl = 0
					acp = 0
					sc_dp3 = 0
					sc_d2e = 0
					sc_roe3 = 0
					sc_roce3 = 0
					sc_sales5 = 0
					sc_profit5 = 0
					sc_peg = 0
					sc_pledge = 0
				else:
					sc_cmp = self.get_sc_cmp_by_sno(isin_code)
					sc_iv = self.get_sc_iv_by_sno(isin_code)
					sc_myavgiv = self.get_sc_myavgiv_by_sno(isin_code)
					upl = self.demat_summary_get_upl_pct_by_isin_code(isin_code)
					acp = self.demat_summary_get_acp_by_isin_code(isin_code)
					sc_dp3 = self.get_sc_dp3_by_sno(isin_code)
					sc_d2e = self.get_sc_d2e_by_sno(isin_code)
					sc_roe3 = self.get_sc_roe3_by_sno(isin_code)
					sc_roce3 = self.get_sc_roce3_by_sno(isin_code)
					sc_sales5 = self.get_sc_sales5_by_sno(isin_code)
					sc_profit5 = self.get_sc_profit5_by_sno(isin_code)
					sc_peg = self.get_sc_peg_by_sno(isin_code)
					sc_pledge = self.get_sc_pledge_by_sno(isin_code)
				
				last_txn_days = self.tbd_last_txn_days[comp_name]
				p_str = self.tbd_isin_name[comp_name]
				p_str += ','
				p_str += isin_code
				p_str += ',' 
				p_str += str(plan_units)
				p_str += ',' 
				p_str += str(demat_units)
				p_str += ',' 
				p_str += str(tbd_units) 
				p_str += ',' 
				p_str += str(tbd_pct) 
				p_str += ',' 
				p_str += self.tbd_demat_last_txn_date[comp_name]
				p_str += ',' 
				p_str += str(last_txn_days)
				p_str += ',' 
				p_str += self.tbd_demat_last_txn_type[comp_name]
				p_str += ',' 
				p_str += self.tbd_captype[comp_name]
				p_str += ',' 
				p_str += str(sc_cmp)
				p_str += ',' 
				p_str += str(sc_myavgiv)
				p_str += ',' 
				p_str += str(sc_mos) +' %'
				p_str += ',' 
				p_str += str(upl)
				p_str += ',' 
				p_str += str(acp)
				p_str += ',' 
				p_str += str(sc_dp3)
				p_str += ',' 
				p_str += str(sc_d2e)
				p_str += ',' 
				p_str += str(sc_roe3)
				p_str += ',' 
				p_str += str(sc_roce3)
				p_str += ',' 
				p_str += str(sc_sales5)
				p_str += ',' 
				p_str += str(sc_profit5)
				p_str += ',' 
				p_str += str(sc_peg)
				p_str += ',' 
				p_str += str(sc_pledge)
				p_str += ',' 
				if sort_sale:
					skip_row = True 
					if sc_dp3 < 6:
						p_str += 'dp3 < 6' 
						p_str += ' and '
						skip_row = False 
					if sc_d2e > 2:
						p_str += 'd2e > 2' 
						p_str += ' and '
						skip_row = False 
					if sc_roe3 < 4:
						p_str += 'roe3 < 4' 
						p_str += ' and '
						skip_row = False 
					if sc_roce3 < 4:
						p_str += 'roce3 < 4' 
						p_str += ' and '
						skip_row = False 
					if sc_sales5 < 0:
						p_str += 'sales5 < 0' 
						p_str += ' and '
						skip_row = False 
					if sc_profit5 < 0:
						p_str += 'profit5 < 0' 
						p_str += ' and '
						skip_row = False 
					if sc_peg > 4:
						p_str += 'peg > 4' 
						p_str += ' and '
						skip_row = False 
					if sc_pledge > 25:
						p_str += 'pledge > 25' 
						p_str += ' and '
						skip_row = False 
					if sc_myavgiv == 0:
						p_str += 'myavgiv eq 0' 
						p_str += ' and '
						skip_row = False 
					if sc_mos < mos: 
						p_str += 'cmp + ' + str(sc_mos) + '%' + '= myavgiv'
						p_str += ' and '
						skip_row = False 
					
					if not skip_row:
						p_str += '\n' 
						fh.write(p_str)
				else:
					if tbd_only :
						passed_cond = tbd_units > 0 
					else:
						passed_cond = True
					
					if apply_cond and passed_cond:
						passed_cond = sc_dp3 >= 6 and sc_d2e <= 2 and sc_roe3 >= 4 and sc_roce3 >= 4 and sc_sales5 > 0 and sc_profit5 > 0 and sc_peg <=4 and sc_mos >= mos 
					if apply_cond and passed_cond :
						p_str += ' Passed as dp3 ge 6 and d2e le 2 and roe3 ge 5 and roce3 ge 4 and sales5 gt 0 and profit5 gt 0 and peg le 4 and pledge le 25'
						p_str += 'and sc_mos ge' + str(mos) +' '
					else:
						check_failed = False
						if sc_dp3 < 6:
							p_str += 'dp3 < 6' 
							p_str += ' and '
							check_failed = True
						if sc_d2e > 2:
							p_str += 'd2e > 2' 
							p_str += ' and '
							check_failed = True
						if sc_roe3 < 4:
							p_str += 'roe3 < 4' 
							p_str += ' and '
							check_failed = True
						if sc_roce3 < 4:
							p_str += 'roce3 < 4' 
							p_str += ' and '
							check_failed = True
						if sc_sales5 < 0:
							p_str += 'sales5 < 0' 
							p_str += ' and '
							check_failed = True
						if sc_profit5 < 0:
							p_str += 'profit5 < 0' 
							p_str += ' and '
							check_failed = True
						if sc_peg > 4:
							p_str += 'peg > 4' 
							p_str += ' and '
							check_failed = True
						if sc_pledge > 25:
							p_str += 'pledge > 25' 
							p_str += ' and '
							check_failed = True
						if sc_myavgiv == 0:
							p_str += 'myavgiv eq 0' 
							p_str += ' and '
							check_failed = True
						if sc_mos >= mos:
							p_str += 'cmp + ' + str(sc_mos) + '%' + ' = myavgiv'
							p_str += ' and '
							check_failed = True
						if tbd_units <= 0:
							p_str += 'tbd_units le 0' 
							p_str += ' and '
							check_failed = True
						if check_failed:
							p_str += 'Failed'
						else:
							p_str += 'Passed'
					
					p_str += '\n' 
					if passed_cond :
						if days_filter:
							if last_txn_days > days_filter :
								fh.write(p_str)
						else:	
							fh.write(p_str)
			except ValueError:
				print 'except : print : ValueError :', comp_name
				traceback.print_exc()
		fh.close()

	def dump_plan_nocond(self, out_filename):
		self.print_tbd_phase1(out_filename, plan_only=True, apply_cond=False)
	def dump_plan_cond(self, out_filename):
		self.print_tbd_phase1(out_filename, plan_only=True)

	def dump_plan_cond_mos(self, out_filename, mos):
		self.print_tbd_phase1(out_filename, plan_only=True, mos=mos)

	def dump_plan_tbd_cond(self, out_filename):
		self.print_tbd_phase1(out_filename, plan_only=True, tbd_only=True)
	def dump_plan_tbd_days_nocond(self, out_filename, days_filter):
		self.print_tbd_phase1(out_filename, plan_only=True, tbd_only=True, days_filter=days_filter, apply_cond=False)

	def dump_plan_tbd_days_cond(self, out_filename, days_filter):
		self.print_tbd_phase1(out_filename, plan_only=True, tbd_only=True, days_filter=days_filter)

	def dump_plan_demat_cond_sale(self, out_filename):
		self.print_tbd_phase1(out_filename, plan_only=True, tbd_only=False, days_filter=None, apply_cond=True, demat_only=True, sort_sale=True)