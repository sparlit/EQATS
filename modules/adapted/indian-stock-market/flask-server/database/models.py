import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
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


from flask_bcrypt import check_password_hash, generate_password_hash
from flask_mongoengine import MongoEngine

db = MongoEngine()


def initialize_db(app):
    db.init_app(app)


class User(db.Document):
    username = db.StringField(required=True, primary_key=True)
    email = db.EmailField(required=True, unique=True)
    password = db.StringField(required=True, min_length=6)
    watchlist = db.ListField(db.StringField())

    def hash_password(self):
        self.password = generate_password_hash(self.password).decode("utf8")

    def check_password(self, password):
        return check_password_hash(self.password, password)


class Script(db.DynamicDocument):
    code = db.StringField(required=True, unique=True)
    url = db.StringField(required=True, unique=True)
    name = db.StringField()
    full_name = db.StringField()
    sector = db.StringField()
    isin = db.StringField()
    NSEID = db.StringField()
    BSEID = db.IntField()
    MKTCAP = db.DecimalField()
    PE = db.DecimalField()
    BV = db.DecimalField()
    DIVPR = db.DecimalField()
    IND_PE = db.DecimalField()
    SC_TTM = db.DecimalField()
    FaceValue = db.DecimalField()
    SHRS = db.DecimalField()
    lastupd = db.DateTimeField()


class Indicies(db.Document):
    stkexchg = db.StringField()
    exchange = db.StringField()
    ind_id = db.StringField()
    history_url = db.StringField()
    lastprice = db.DecimalField()
    change = db.DecimalField()
    percentchange = db.DecimalField()
    open = db.DecimalField()
    high = db.DecimalField()
    low = db.DecimalField()
    prevclose = db.DecimalField()
    yearlyhigh = db.DecimalField()
    yearlylow = db.DecimalField()
    ytd = db.DecimalField()
    lastupdated = db.DateTimeField()
    history = db.ListField()


class Trade(db.Document):
    code = db.StringField(required=True)
    full_name = db.StringField(required=True)
    trade = db.StringField(required=True)
    user = db.ReferenceField("User", required=True)
    qty = db.DecimalField(required=True)
    price = db.DecimalField(required=True)
    date = db.DateTimeField(required=True)
