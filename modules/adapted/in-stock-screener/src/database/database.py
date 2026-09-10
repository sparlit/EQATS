
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


import os
import sqlite3

from config import *

class Database(Config):
	def __init__(self):
		super(Database, self).__init__()
		self.debug_level = 0 
		self.db_filepath = os.path.join(self.get_db_files(), self.DB_FILENAME) 
		db_exists = os.path.exists(self.db_filepath)
		if db_exists:
			print 'db exists'
		else:
			print 'db new'
		self.db_conn = sqlite3.connect(self.db_filepath)
		
		# sqlite3.ProgrammingError: You must not use 8-bit bytestrings unless you use a text_factory that can interpret 8-bit bytestrings (like text_factory = str). It is highly recommended that you instead just switch your application to Unicode strings.
		
		self.db_conn.text_factory = str

	def set_debug_level(self, debug_level):
 		self.debug_level = debug_level

	def db_get_conn(self):
		return self.db_conn

	def db_table_count_rows(self, table):
		SQL = """select count(*) from {}""".format(table)
		print 'count_amfi_db sql', SQL
		# SQL = """select count(*) from amfi"""
		cursor = self.db_conn.cursor()
		cursor.execute(SQL)
		result = cursor.fetchone()
		row_count = result[0]
		if self.debug_level > 0 :
			print 'count_amfi_db : row_count : ', row_count 
		return row_count

	def db_table_load(self, table):
		SQL = """select * from {}""".format(table)
		print 'db_table_load sql', SQL
		cursor = self.db_conn.cursor()
		cursor.execute(SQL)
		return cursor