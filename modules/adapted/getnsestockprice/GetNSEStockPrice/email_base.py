
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


import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import config

def send_mail(message,receivers=config['smtp_receivers']):
    """
        Module that sends emails. 
        Message should be a dictionary containing the following keys:
            subject -> Subject of the email
            text -> The plain text part of the email
        uses options from config.py
    """
    sender = config['smtp_sender']
    print sender
    print receivers
    print message
    try:
        smtpObj = smtplib.SMTP_SSL(config['smtp_server'],config['smtp_port'])
        smtpObj.login(config['smtp_login'],config['smtp_password'])
        if not receivers:
            return True
        smtpObj.sendmail(sender, receivers, message)
        smtpObj.quit()
        return True 
    except Exception, exc:
         print >> sys.stderr, "Exception From email_base"
         print >> sys.stderr, exc 
         return False
if __name__ == '__main__':
    send_mail('Test message')