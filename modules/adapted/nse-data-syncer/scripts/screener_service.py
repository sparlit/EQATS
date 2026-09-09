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


#!/usr/bin/env python3
"""
Screener.in Data Collection Service
Comprehensive web scraping service for Indian stock market data
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)


class ScreenerService:
    """Service to collect data from Screener.in"""

    def __init__(self, headless: bool = True):
        self.base_url = "https://www.screener.in"
        self.login_url = f"{self.base_url}/login/"
        self.session = requests.Session()
        self.driver = None
        self.is_logged_in = False
        self.headless = headless

        # Set up Chrome options
        self.chrome_options = Options()
        if headless:
            self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )

    def __enter__(self):
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=self.chrome_options)
        # Without this, a single slow/hung page can block driver.get() forever,
        # stalling an entire batch run (Selenium has no default timeout).
        self.driver.set_page_load_timeout(20)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            self.driver.quit()

    def login(self, username: str, password: str) -> bool:
        """Login to Screener.in"""
        try:
            logger.info("Logging into Screener.in...")
            self.driver.get(self.login_url)

            # Wait for login form to load
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.NAME, "username")))

            # Fill login form
            username_field = self.driver.find_element(By.NAME, "username")
            password_field = self.driver.find_element(By.NAME, "password")

            username_field.send_keys(username)
            password_field.send_keys(password)

            # Submit form
            login_button = self.driver.find_element(By.XPATH, "//button[@type='submit']")
            login_button.click()

            # Wait for login to complete
            time.sleep(3)

            # Check if login was successful
            if "login" not in self.driver.current_url.lower():
                self.is_logged_in = True
                logger.info("✅ Successfully logged into Screener.in")
                return True
            logger.error("❌ Login failed - still on login page")
            return False

        except Exception as e:
            logger.exception(f"❌ Login error: {e!s}")
            return False

    def get_stock_data(self, symbol: str) -> dict[str, Any]:
        """Get comprehensive stock data from Screener.in"""
        if not self.is_logged_in:
            logger.error("Not logged in. Please login first.")
            return {}

        try:
            # Convert symbol to Screener.in format (remove .NS, .BO)
            clean_symbol = symbol.replace(".NS", "").replace(".BO", "")
            url = f"{self.base_url}/company/{clean_symbol}/consolidated/"

            logger.info(f"Fetching data for {symbol} from {url}")
            self.driver.get(url)
            time.sleep(2)

            # Check if page loaded successfully
            if "company" not in self.driver.current_url.lower():
                logger.warning(f"Could not load company page for {symbol}")
                return {}

            stock_data = {
                "symbol": symbol,
                "name": self._extract_company_name(),
                "basic_info": self._extract_basic_info(),
                "sector_info": self._extract_sector_info(),  # Added sector info
                "quarterly_results": self._extract_quarterly_results(),
                "profit_loss": self._extract_profit_loss(),
                "balance_sheet": self._extract_balance_sheet(),
                "cash_flow": self._extract_cash_flow(),
                "ratios": self._extract_ratios(),
                "shareholding_pattern": self._extract_shareholding_pattern(),
                "announcements": self._extract_announcements(),
                "credit_ratings": self._extract_credit_ratings(),
                "concalls": self._extract_concall_transcripts(),
            }

            logger.info(f"✅ Successfully collected data for {symbol}")
            return stock_data

        except Exception as e:
            logger.exception(f"❌ Error collecting data for {symbol}: {e!s}")
            return {}

    def _extract_company_name(self) -> str:
        """Extract company name from page"""
        try:
            # Try multiple selectors for company name
            selectors = [
                "//h1",
                "//div[contains(@class, 'company-name')]//h1",
                "//div[contains(@class, 'company-info')]//h1",
                "//h1[contains(@class, 'company-name')]",
            ]

            for selector in selectors:
                try:
                    name_element = self.driver.find_element(By.XPATH, selector)
                    name = name_element.text.strip()
                    if name and len(name) > 2:
                        return name
                except:
                    continue

            return ""
        except:
            return ""

    def _extract_basic_info(self) -> dict[str, Any]:
        """Extract basic stock information"""
        try:
            info = {}

            # Market cap, current price, etc.
            info_elements = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'company-info')]//div")

            for element in info_elements:
                text = element.text.strip()
                if "Market Cap" in text:
                    info["market_cap"] = self._extract_number(text)
                elif "Current Price" in text:
                    info["current_price"] = self._extract_number(text)
                elif "High / Low" in text:
                    high_low = text.split("₹")[1].strip()
                    info["high_52_week"] = self._extract_number(high_low.split("/")[0])
                    info["low_52_week"] = self._extract_number(high_low.split("/")[1])
                elif "Stock P/E" in text:
                    info["pe_ratio"] = self._extract_number(text)
                elif "Book Value" in text:
                    info["book_value"] = self._extract_number(text)
                elif "Dividend Yield" in text:
                    info["dividend_yield"] = self._extract_number(text)
                elif "ROCE" in text:
                    info["roce"] = self._extract_number(text)
                elif "ROE" in text:
                    info["roe"] = self._extract_number(text)
                elif "Face Value" in text:
                    info["face_value"] = self._extract_number(text)

            return info

        except Exception as e:
            logger.exception(f"Error extracting basic info: {e!s}")
            return {}

    def _extract_quarterly_results(self) -> pd.DataFrame:
        """Extract quarterly results table"""
        try:
            # Look for quarterly results table
            tables = self.driver.find_elements(By.TAG_NAME, "table")

            for table in tables:
                table_text = table.text
                if "Sales" in table_text and "Expenses" in table_text and "Operating Profit" in table_text:
                    # Found quarterly results table
                    try:
                        df = pd.read_html(table.get_attribute("outerHTML"))[0]
                        logger.debug(f"Found quarterly results table with {len(df)} rows and {len(df.columns)} columns")
                        return df
                    except Exception as e:
                        logger.debug(f"Error parsing quarterly results table: {e!s}")
                        continue

            logger.debug("No quarterly results table found")
            return pd.DataFrame()

        except Exception as e:
            logger.exception(f"Error extracting quarterly results: {e!s}")
            return pd.DataFrame()

    def _extract_profit_loss(self) -> pd.DataFrame:
        """Extract profit & loss statement"""
        try:
            # Try to navigate to P&L section
            pnl_selectors = [
                "//a[contains(text(), 'Profit & Loss')]",
                "//a[contains(text(), 'P&L')]",
                "//a[contains(text(), 'Income Statement')]",
            ]

            for selector in pnl_selectors:
                try:
                    pnl_link = self.driver.find_element(By.XPATH, selector)
                    pnl_link.click()
                    time.sleep(2)
                    break
                except:
                    continue
            else:
                # If no navigation link found, try to find P&L table on current page
                logger.debug("No P&L navigation link found, searching current page")

            # Extract P&L table
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            for table in tables:
                if "Sales" in table.text and "Profit" in table.text:
                    return pd.read_html(table.get_attribute("outerHTML"))[0]

            return pd.DataFrame()

        except Exception as e:
            logger.exception(f"Error extracting P&L: {e!s}")
            return pd.DataFrame()

    def _extract_balance_sheet(self) -> pd.DataFrame:
        """Extract balance sheet"""
        try:
            # Try to navigate to Balance Sheet section
            bs_selectors = ["//a[contains(text(), 'Balance Sheet')]", "//a[contains(text(), 'Balance')]"]

            for selector in bs_selectors:
                try:
                    bs_link = self.driver.find_element(By.XPATH, selector)
                    bs_link.click()
                    time.sleep(2)
                    break
                except:
                    continue
            else:
                # If no navigation link found, try to find balance sheet table on current page
                logger.debug("No Balance Sheet navigation link found, searching current page")

            # Extract balance sheet table
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            for table in tables:
                if "Assets" in table.text and "Liabilities" in table.text:
                    return pd.read_html(table.get_attribute("outerHTML"))[0]

            return pd.DataFrame()

        except Exception as e:
            logger.exception(f"Error extracting balance sheet: {e!s}")
            return pd.DataFrame()

    def _extract_cash_flow(self) -> pd.DataFrame:
        """Extract cash flow statement"""
        try:
            # Navigate to Cash Flow section
            cf_link = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Cash Flow')]")
            cf_link.click()
            time.sleep(2)

            # Extract cash flow table
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            for table in tables:
                if "Operating" in table.text and "Investing" in table.text:
                    return pd.read_html(table.get_attribute("outerHTML"))[0]

            return pd.DataFrame()

        except Exception as e:
            logger.exception(f"Error extracting cash flow: {e!s}")
            return pd.DataFrame()

    def _extract_ratios(self) -> dict[str, float]:
        """Extract key financial ratios"""
        try:
            ratios = {}

            # Look for ratios section
            ratio_elements = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'ratios')]//div")

            for element in ratio_elements:
                text = element.text.strip()
                if ":" in text:
                    key, value = text.split(":", 1)
                    key = key.strip().lower().replace(" ", "_")
                    value = self._extract_number(value)
                    if value is not None:
                        ratios[key] = value

            return ratios

        except Exception as e:
            logger.exception(f"Error extracting ratios: {e!s}")
            return {}

    def _extract_shareholding_pattern(self) -> pd.DataFrame:
        """Extract shareholding pattern"""
        try:
            # First, try to navigate directly to the shareholding section using the URL anchor
            current_url = self.driver.current_url
            if "#shareholding" not in current_url:
                shareholding_url = current_url + "#shareholding"
                logger.debug(f"Navigating to shareholding section: {shareholding_url}")
                self.driver.get(shareholding_url)
                time.sleep(3)  # Wait for page to load

            # Look for shareholding tables on current page
            logger.debug("Searching for shareholding pattern data on current page...")
            tables = self.driver.find_elements(By.TAG_NAME, "table")

            for table in tables:
                table_text = table.text
                # Look for key shareholding pattern indicators
                if any(keyword in table_text for keyword in ["Promoters", "FIIs", "DIIs", "Public", "Government"]):
                    try:
                        df = pd.read_html(table.get_attribute("outerHTML"))[0]
                        logger.debug(
                            f"Found potential shareholding pattern table with {len(df)} rows and {len(df.columns)} columns"
                        )

                        # Validate that this looks like a shareholding pattern table
                        if len(df.columns) >= 3 and any("Promoters" in str(col) for col in df.columns):
                            logger.info(
                                f"✅ Found shareholding pattern table: {len(df)} rows, {len(df.columns)} columns"
                            )
                            return df
                        logger.debug("Table found but doesn't look like shareholding pattern")
                        continue

                    except Exception as e:
                        logger.debug(f"Error parsing shareholding pattern table: {e!s}")
                        continue

            # If no table found with anchor navigation, try scrolling to find shareholding section
            logger.debug("No shareholding table found with anchor navigation, trying to scroll and find...")
            try:
                # Scroll down to find shareholding section
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

                # Look for shareholding section by text
                shareholding_elements = self.driver.find_elements(
                    By.XPATH, "//*[contains(text(), 'Shareholding Pattern') or contains(text(), 'Shareholding')]"
                )

                if shareholding_elements:
                    logger.debug(f"Found {len(shareholding_elements)} shareholding elements")
                    # Scroll to the first shareholding element
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", shareholding_elements[0])
                    time.sleep(2)

                    # Now look for tables near this section
                    tables = self.driver.find_elements(By.TAG_NAME, "table")
                    for table in tables:
                        table_text = table.text
                        if any(
                            keyword in table_text for keyword in ["Promoters", "FIIs", "DIIs", "Public", "Government"]
                        ):
                            try:
                                df = pd.read_html(table.get_attribute("outerHTML"))[0]
                                logger.info(
                                    f"✅ Found shareholding pattern table after scrolling: {len(df)} rows, {len(df.columns)} columns"
                                )
                                return df
                            except Exception as e:
                                logger.debug(f"Error parsing shareholding table after scrolling: {e!s}")
                                continue

            except Exception as e:
                logger.debug(f"Error scrolling to find shareholding section: {e!s}")

            # If still no table found, try clicking on shareholding links
            logger.debug("No shareholding table found with scrolling, trying link clicks...")
            sh_selectors = [
                "//a[contains(text(), 'Shareholding Pattern')]",
                "//a[contains(text(), 'Shareholding')]",
                "//a[contains(text(), 'Shareholders')]",
                "//a[contains(text(), 'Shareholding Pattern')]",
            ]

            for selector in sh_selectors:
                try:
                    sh_link = self.driver.find_element(By.XPATH, selector)
                    logger.debug(f"Found shareholding link with selector: {selector}")
                    sh_link.click()
                    time.sleep(3)  # Wait longer for page to load

                    # Now search for tables on this page
                    tables = self.driver.find_elements(By.TAG_NAME, "table")
                    for table in tables:
                        table_text = table.text
                        if any(
                            keyword in table_text for keyword in ["Promoters", "FIIs", "DIIs", "Public", "Government"]
                        ):
                            try:
                                df = pd.read_html(table.get_attribute("outerHTML"))[0]
                                logger.info(
                                    f"✅ Found shareholding pattern table after navigation: {len(df)} rows, {len(df.columns)} columns"
                                )
                                return df
                            except Exception as e:
                                logger.debug(f"Error parsing shareholding table after navigation: {e!s}")
                                continue

                    logger.debug(f"Navigation successful with {selector} but no shareholding table found")
                    break

                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e!s}")
                    continue

            # If still no table found, try to extract from page content
            logger.debug("No shareholding pattern table found, trying to extract from page content")
            return self._extract_shareholding_from_content()

        except Exception as e:
            logger.exception(f"Error extracting shareholding pattern: {e!s}")
            return pd.DataFrame()

    def _extract_shareholding_from_content(self) -> pd.DataFrame:
        """Extract shareholding pattern from page content when table is not available"""
        try:
            # Look for shareholding information in the page content
            shareholding_data = {}

            # Get both page source and visible text
            page_source = self.driver.page_source
            visible_text = self.driver.find_element(By.TAG_NAME, "body").text

            # Common patterns for shareholding data - try multiple formats
            patterns = [
                # Percentage patterns
                (r"Promoters[:\s]*([\d.]+)%?", "Promoters"),
                (r"FIIs[:\s]*([\d.]+)%?", "FIIs"),
                (r"DIIs[:\s]*([\d.]+)%?", "DIIs"),
                (r"Government[:\s]*([\d.]+)%?", "Government"),
                (r"Public[:\s]*([\d.]+)%?", "Public"),
                (r"Retail[:\s]*([\d.]+)%?", "Retail"),
                (r"Institutions[:\s]*([\d.]+)%?", "Institutions"),
                # Alternative patterns
                (r"Promoter[:\s]*([\d.]+)%?", "Promoters"),
                (r"Foreign[:\s]*([\d.]+)%?", "FIIs"),
                (r"Domestic[:\s]*([\d.]+)%?", "DIIs"),
                # Look for patterns in visible text
                (r"Promoters[:\s]*([\d.]+)", "Promoters"),
                (r"FIIs[:\s]*([\d.]+)", "FIIs"),
                (r"DIIs[:\s]*([\d.]+)", "DIIs"),
            ]

            # Search in both page source and visible text
            for text_source in [page_source, visible_text]:
                for pattern, category in patterns:
                    import re

                    matches = re.findall(pattern, text_source, re.IGNORECASE)
                    if matches:
                        try:
                            value = float(matches[0])
                            if value > 0 and value <= 100:  # Valid percentage
                                shareholding_data[category] = value
                                logger.debug(f"Found {category}: {value}%")
                        except:
                            continue

            # Also try to find shareholding data in specific divs or sections
            try:
                # Look for shareholding info in specific divs
                shareholding_divs = self.driver.find_elements(
                    By.XPATH,
                    "//div[contains(text(), 'Shareholding') or contains(text(), 'Promoters') or contains(text(), 'FIIs')]",
                )

                for div in shareholding_divs:
                    div_text = div.text
                    logger.debug(f"Found potential shareholding div: {div_text[:100]}...")

                    # Extract percentages from this div
                    for pattern, category in patterns:
                        matches = re.findall(pattern, div_text, re.IGNORECASE)
                        if matches:
                            try:
                                value = float(matches[0])
                                if value > 0 and value <= 100 and category not in shareholding_data:
                                    shareholding_data[category] = value
                                    logger.debug(f"Found {category}: {value}% in div")
                            except:
                                continue

            except Exception as e:
                logger.debug(f"Error searching divs for shareholding data: {e!s}")

            if shareholding_data:
                # Create a simple DataFrame from extracted data
                df = pd.DataFrame([shareholding_data])
                logger.info(f"✅ Extracted shareholding data from page content: {shareholding_data}")
                return df
            logger.debug("No shareholding data found in page content")

            return pd.DataFrame()

        except Exception as e:
            logger.debug(f"Error extracting shareholding from content: {e!s}")
            return pd.DataFrame()

    def _extract_announcements(self) -> list[dict[str, str]]:
        """Extract company announcements"""
        try:
            announcements = []

            # Navigate to announcements section
            ann_link = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Announcements')]")
            ann_link.click()
            time.sleep(2)

            # Extract announcements
            ann_elements = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'announcement')]")

            for element in ann_elements:
                try:
                    title = element.find_element(By.XPATH, ".//div[contains(@class, 'title')]").text.strip()
                    date = element.find_element(By.XPATH, ".//div[contains(@class, 'date')]").text.strip()
                    description = element.find_element(By.XPATH, ".//div[contains(@class, 'description')]").text.strip()

                    announcements.append({"title": title, "date": date, "description": description})
                except:
                    continue

            return announcements

        except Exception as e:
            logger.exception(f"Error extracting announcements: {e!s}")
            return []

    def _extract_credit_ratings(self) -> list[dict[str, str]]:
        """Extract credit ratings"""
        try:
            ratings = []

            # Navigate to credit ratings section
            cr_link = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Credit Ratings')]")
            cr_link.click()
            time.sleep(2)

            # Extract ratings
            rating_elements = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'rating')]")

            for element in rating_elements:
                try:
                    agency = element.find_element(By.XPATH, ".//div[contains(@class, 'agency')]").text.strip()
                    rating = element.find_element(By.XPATH, ".//div[contains(@class, 'rating')]").text.strip()
                    date = element.find_element(By.XPATH, ".//div[contains(@class, 'date')]").text.strip()

                    ratings.append({"agency": agency, "rating": rating, "date": date})
                except:
                    continue

            return ratings

        except Exception as e:
            logger.exception(f"Error extracting credit ratings: {e!s}")
            return []

    def _extract_concall_transcripts(self) -> list[dict[str, str]]:
        """Extract concall transcripts"""
        try:
            transcripts = []

            # Navigate to concall section
            cc_link = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Concall')]")
            cc_link.click()
            time.sleep(2)

            # Extract concall info
            cc_elements = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'concall')]")

            for element in cc_elements:
                try:
                    quarter = element.find_element(By.XPATH, ".//div[contains(@class, 'quarter')]").text.strip()
                    date = element.find_element(By.XPATH, ".//div[contains(@class, 'date')]").text.strip()

                    transcripts.append({"quarter": quarter, "date": date})
                except:
                    continue

            return transcripts

        except Exception as e:
            logger.exception(f"Error extracting concall transcripts: {e!s}")
            return []

    # Screener's own classification-level names, in order, mapped to our
    # 4-level schema (matches how the BSE CSV's Sector Name / Industry New
    # Name / Igroup Name / ISubgroup Name already line up - see
    # scripts/update_sectors_from_bse.py).
    _SECTOR_LEVEL_TO_FIELD = {
        "Broad Sector": "sector",
        "Sector": "subsector1",
        "Broad Industry": "subsector2",
        "Industry": "subsector3",
    }

    def _extract_sector_info(self) -> dict[str, str]:
        """Extract the 4-level sector/industry classification from the
        "Peer comparison" breadcrumb. Each level is an <a> tag whose `title`
        attribute names the level ("Broad Sector", "Sector", "Broad
        Industry", "Industry") - generic across every company's page,
        unlike the old keyword-matching approach this replaced."""
        sector_info = {"sector": "", "subsector1": "", "subsector2": "", "subsector3": ""}
        try:
            for level_title, field in self._SECTOR_LEVEL_TO_FIELD.items():
                try:
                    element = self.driver.find_element(By.XPATH, f"//a[@title='{level_title}']")
                    text = element.text.strip()
                    if text:
                        sector_info[field] = text
                except NoSuchElementException:
                    continue

            if any(sector_info.values()):
                logger.info(f"Extracted sector info: {sector_info}")
            else:
                logger.warning("No sector classification breadcrumb found on page")
            return sector_info

        except Exception as e:
            logger.exception(f"Error extracting sector info: {e!s}")
            return sector_info

    def _extract_number(self, text: str) -> float | None:
        """Extract number from text"""
        try:
            # Remove currency symbols and commas
            cleaned = re.sub(r"[₹,,\s]", "", text)
            # Extract first number found
            match = re.search(r"[\d,]+\.?\d*", cleaned)
            if match:
                return float(match.group().replace(",", ""))
            return None
        except:
            return None

    def get_nifty50_symbols(self) -> list[str]:
        """Get list of Nifty 50 symbols"""
        return [
            "ABB.NS",
            "ACC.NS",
            "ADANIGREEN.NS",
            "ADANIPORTS.NS",
            "AMBUJACEM.NS",
            "ASIANPAINT.NS",
            "AXISBANK.NS",
            "BAJAJ-AUTO.NS",
            "BAJAJFINSV.NS",
            "BAJFINANCE.NS",
            "BANDHANBNK.NS",
            "BANKBARODA.NS",
            "BERGEPAINT.NS",
            "BHARTIARTL.NS",
            "BIOCON.NS",
            "BPCL.NS",
            "BRITANNIA.NS",
            "CIPLA.NS",
            "COALINDIA.NS",
            "COLPAL.NS",
            "CONCOR.NS",
            "DABUR.NS",
            "DIVISLAB.NS",
            "DLF.NS",
            "DRREDDY.NS",
            "EICHERMOT.NS",
            "GAIL.NS",
            "GLAND.NS",
            "GLENMARK.NS",
            "GMRINFRA.NS",
            "GODREJCP.NS",
            "GRASIM.NS",
            "HAVELLS.NS",
            "HEROMOTOCO.NS",
            "HINDALCO.NS",
            "HINDPETRO.NS",
            "HINDUNILVR.NS",
            "HDFCBANK.NS",
            "HDFCLIFE.NS",
            "ICICIBANK.NS",
            "ICICIPRULI.NS",
            "INDHOTEL.NS",
            "INDIGO.NS",
            "INDUSINDBK.NS",
            "INFY.NS",
            "IOC.NS",
            "ITC.NS",
            "JSWSTEEL.NS",
            "JUBLFOOD.NS",
            "KOTAKBANK.NS",
            "LT.NS",
            "LUPIN.NS",
            "M&M.NS",
            "MARICO.NS",
            "MARUTI.NS",
            "MFSL.NS",
            "NAUKRI.NS",
            "NAVINFLUOR.NS",
            "NESTLEIND.NS",
            "NMDC.NS",
            "ONGC.NS",
            "PIIND.NS",
            "PIDILITIND.NS",
            "PNB.NS",
            "POWERGRID.NS",
            "RELIANCE.NS",
            "SBICARD.NS",
            "SBILIFE.NS",
            "SBIN.NS",
            "SHREECEM.NS",
            "SIEMENS.NS",
            "SRF.NS",
            "SUNPHARMA.NS",
            "TATACONSUM.NS",
            "TATAMOTORS.NS",
            "TATASTEEL.NS",
            "TCS.NS",
            "TECHM.NS",
            "TITAN.NS",
            "TORNTPHARM.NS",
            "ULTRACEMCO.NS",
            "UPL.NS",
            "VEDL.NS",
            "WIPRO.NS",
            "ZEEL.NS",
        ]
