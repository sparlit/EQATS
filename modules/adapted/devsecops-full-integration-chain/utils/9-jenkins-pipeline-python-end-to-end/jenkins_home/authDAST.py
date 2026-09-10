import datetime
import json
import random
import string
import subprocess
import sys
from typing import TYPE_CHECKING

import pytz
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    else:
        if dt.tzinfo is None:
            dt = ist.localize(dt)
        now = dt.astimezone(ist)
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


def random_string(string_length: int) -> str:
    letters = string.ascii_letters
    return "".join(random.choice(letters) for _ in range(string_length))


def bash_command(cmd: str) -> None:
    subprocess.Popen(cmd, shell=True, executable="/bin/bash")


def main() -> None:
    myusername = random_string(8)
    mypassword = random_string(12)

    if len(sys.argv) < 4:
        print("1. Provide the ip address for selenium remote server!")
        print("2. Provide the ip address for target DAST scan!")
        print("3. Provide the output location of html report!")
        sys.exit(1)

    selenium_host = sys.argv[1]
    target_host = sys.argv[2]
    # output_location = sys.argv[3]  # unused but kept for compatibility

    chrome_options = ChromeOptions()
    driver: WebDriver = webdriver.Remote(command_executor=f"http://{selenium_host}:4444/wd/hub", options=chrome_options)

    try:
        driver.get(f"http://{target_host}:10007/login")

        register_button = driver.find_element(By.XPATH, "/html/body/div/div/div/form/center[3]/a")
        register_button.click()
        print(f"we're at: {driver.current_url}")

        print("creating a user..")
        username = driver.find_element(By.NAME, "username")
        password1 = driver.find_element(By.NAME, "password1")
        password2 = driver.find_element(By.NAME, "password2")

        username.clear()
        username.send_keys(myusername)
        password1.clear()
        password1.send_keys(mypassword)
        password2.clear()
        password2.send_keys(mypassword)
        password2.send_keys(Keys.RETURN)
        login = driver.find_element(By.XPATH, "/html/body/div/div/div/center[2]/h4")
        assert "Login" in login.text

        print("created user")

        driver.get(f"http://{target_host}:10007/login")
        print(f"we're at: {driver.current_url}")
        username = driver.find_element(By.NAME, "username")
        password = driver.find_element(By.NAME, "password")
        username.clear()
        username.send_keys(myusername)
        password.clear()
        password.send_keys(mypassword)
        password.send_keys(Keys.RETURN)
        header = driver.find_element(By.XPATH, "/html/body/div/div/div[1]/h1")
        assert "Last gossips" in header.text
        print("logged in successfully.. getting cookie")

        cookies_list = driver.get_cookies()
        for cookie in cookies_list:
            print(cookie)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
