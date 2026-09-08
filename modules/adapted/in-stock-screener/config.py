
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
import sys

from dateutil.relativedelta import relativedelta
import datetime

class Config(object):
	def __init__(self):
		super(Config, self).__init__()
		self.DB_FILENAME = 'equity.sqlite3'
		# started investment in year 2017
		start_date = datetime.date(2017, 1, 1)
		end_date = datetime.date.today()
		self.INVEST_YEARS = relativedelta(end_date, start_date).years
		self.INVEST_YEARS += 1
		# print 'investing for ', self.INVEST_YEARS, ' years'

	def get_root(self):
		# print globals()
		# print '__file__ : ', __file__
		config_root = os.path.abspath(os.path.dirname(__file__))
		# print config_root
		return config_root

	def get_src(self):
		return os.path.join(self.get_root(), 'src') 
	
	def get_data(self):
		return os.path.join(self.get_root(), 'input-global-data') 

	def get_reports(self):
		return os.path.join(self.get_root(), 'output-global-reports') 

	def get_profile_data(self):
		return os.path.join(self.get_root(), 'input-user-data') 

	def get_profile_reports(self):
		return os.path.join(self.get_root(), 'output-user-reports') 

	def get_db_files(self):
		return os.path.join(self.get_root(), 'db-files')
 
	def get_db_schema(self):
		return os.path.join(self.get_root(), 'db-schema') 

if __name__ == "__main__":
	import config
	config = config.Config();

	cmd = sys.argv[1]
	if cmd == "root" : 
		print config.get_root()
	elif cmd == "src" : 
		print config.get_src()
	elif cmd == "data" : 
		print config.get_data()
	elif cmd == "reports" : 
		print config.get_reports()
	elif cmd == "profile_data" : 
		print config.get_profile_data()
	elif cmd == "profile_reports" : 
		print config.get_profile_reports()
	elif cmd == "db_files" : 
		print config.get_db_files()
	elif cmd == "db_schema" : 
		print config.get_db_schema()