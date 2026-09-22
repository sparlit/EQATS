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


import json
import random
import string
import subprocess
import sys

from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.keys import Keys


def randomString(stringLength):
    letters = string.ascii_letters
    return "".join(random.choice(letters) for i in range(stringLength))


def bash_command(cmd):
    subprocess.Popen(cmd, shell=True, executable="/bin/bash")
    # subprocess.Popen(['/bin/bash', '-c', cmd])


myusername = randomString(8)
mypassword = randomString(12)

if len(sys.argv) < 4:
    print("1. Provide the ip address for selenium remote server!")
    print("2. Provide the ip address for target DAST scan!")
    print("3. Provide the output location of html report!")
    sys.exit(1)

driver = webdriver.Remote("http://" + sys.argv[1] + ":4444/wd/hub", DesiredCapabilities.CHROME)

driver.get("http://" + sys.argv[2] + ":10007/login")

registerbutton = driver.find_element_by_xpath("/html/body/div/div/div/form/center[3]/a")
registerbutton.click()
print("we're at: " + driver.current_url)

print("creating a user..")
username = driver.find_element_by_name("username")
password1 = driver.find_element_by_name("password1")
password2 = driver.find_element_by_name("password2")

username.clear()
username.send_keys(myusername)
password1.clear()
password1.send_keys(mypassword)
password2.clear()
password2.send_keys(mypassword)
password2.send_keys(Keys.RETURN)
login = driver.find_element_by_xpath("/html/body/div/div/div/center[2]/h4")
assert "Login" in login.text

print("created user")

driver.get("http://" + sys.argv[2] + ":10007/login")
print("we're at: " + driver.current_url)
username = driver.find_element_by_name("username")
password = driver.find_element_by_name("password")
username.clear()
username.send_keys(myusername)
password.clear()
password.send_keys(mypassword)
password.send_keys(Keys.RETURN)
header = driver.find_element_by_xpath("/html/body/div/div/div[1]/h1")
assert "Last gossips" in header.text
print("logged in successfully.. getting cookie")

nikto_string = "STATIC-COOKIE="
cookies_list = driver.get_cookies()
for cookie in cookies_list:
    nikto_string += '"' + cookie["name"] + '"='
    nikto_string += '"' + cookie["value"] + '"'
bash_command("cp /etc/nikto/config.txt ~/nikto-config.txt")
bash_command("echo '" + nikto_string + "' >> ~/nikto-config.txt")
print("added cookie to nikto config file to carry out authenticated scan..")
bash_command(
    "nikto -ask no -config ~/nikto-config.txt -Format html -h http://"
    + sys.argv[2]
    + ":10007/gossip -output "
    + sys.argv[3]
)
