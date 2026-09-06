import os
import sqlite3

from database.database import *

class Schema(Database):
	def __init__(self):
		super(Schema, self).__init__()
 		self.debug_level = 0 

	def set_debug_level(self, debug_level):
 		self.debug_level = debug_level

	def create_schema(self, schema_filename):
		print 'Creating schema'
		with open(schema_filename, 'rt') as f:
			schema = f.read()
		# cursor = conn.cursor()
		self.db_conn.executescript(schema)
		
