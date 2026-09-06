#!/usr/bin/python

import sys
import re
import csv
import traceback

class Demat:

	def __init__(self, debug_level, filename):
		self.buy_quantity	= {}
		self.sale_quantity	= {}
		self.buy_price	= {}
		self.sale_price	= {}
		self.last_buy_date = {}
		self.last_sale_date = {}
		self.filename = filename
		self.debug_level = debug_level 

	def load_row(self, row):
		try:
			row_list = row

			comp_name = row_list[1]
			# skip header
			if comp_name == "Company Name":
				return

			quantity = int(row_list[4])
                        price = int(float(row_list[5])) * quantity
		        last_txn_date = row_list[12]
			if row_list[3] == "Buy":
				if comp_name in self.buy_quantity:
					self.buy_quantity[comp_name] += quantity
					self.buy_price[comp_name] += price
				else:
					self.buy_quantity[comp_name] = quantity
					self.buy_price[comp_name] = price

				self.last_buy_date[comp_name] = last_txn_date
			else:
				if comp_name in self.sale_quantity:
					self.sale_quantity[comp_name] += quantity
					self.sale_price[comp_name] += price
				else:
					self.sale_quantity[comp_name] = quantity
					self.sale_price[comp_name] = price

				self.last_sale_date[comp_name] = last_txn_date
		except:
			print "Unexpected error:", sys.exc_info()

	def load_data(self):
		with open(self.filename, 'r') as csvfile:
			reader = csv.reader(csvfile)
			for row in reader:
				self.load_row(row)

	def get_buy_quantity(self, name):
		if name in self.buy_quantity:
			return self.buy_quantity[name]	
		else:
			if self.debug_level > 0:
				print 'invalid key :', name
			return 0

	def get_sale_quantity(self, name):
		if name in self.sale_quantity:
			return self.sale_quantity[name]	
		else:
			if self.debug_level > 0:
				print 'invalid key :', name
			return 0

	def get_comp_quantity(self, name):
		return get_buy_quantity(name) - get_sale_quantity(name)

	def get_buy_price(self, name):
		if name in self.buy_price:
			return self.buy_price[name]	
		else:
			if self.debug_level > 0:
				print 'invalid key :', name
			return 0

	def get_sale_price(self, name):
		if name in self.sale_price:
			return self.sale_price[name]	
		else:
			if self.debug_level > 0:
				print 'invalid key :', name
			return 0

	def get_comp_price(self, name):
		return get_buy_price(name) - get_sale_price(name)

	def get_comp_quantity(self, name):
		return get_comp_price(self, name)/1000

	def size_buy_data(self):
		print len(self.buy_quantity)

	def size_sale_data(self):
		print len(self.sale_quantity)

	def print_comp_data(self):
		print "Buy data"
		print self.buy_quantity
		print "Sale data"
		print self.sale_quantity
		print "Buy Price"
		print self.buy_price
		print "Sale Price"
		print self.sale_price
		print "Last Buy Date"
		print self.last_buy_date
		print "Last Sale Date"
		print self.last_sale_date
