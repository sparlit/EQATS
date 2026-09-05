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
