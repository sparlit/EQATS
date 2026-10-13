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


"""
 *  Project             :   Screenipy
 *  Author              :   Pranjal Joshi
 *  Created             :   21/04/2021
 *  Description         :   Class for handling OTA updates
"""

import subprocess
import sys

import requests
from classes.ColorText import colorText
from classes.Utility import isDocker, isGui


class OTAUpdater:
    developmentVersion = "d"

    # Download and replace exe through other process for Windows
    def updateForWindows(url):
        batFile = (
            """@echo off
color a
echo [+] Screenipy Software Updater!
echo [+] Downloading Software Update...
echo [+] This may take some time as per your Internet Speed, Please Wait...
curl -o screenipy.exe -L """
            + url
            + """
echo [+] Newly downloaded file saved in %cd%
echo [+] Software Update Completed! Run'screenipy.exe' again as usual to continue..
pause
del updater.bat & exit
        """
        )
        f = open("updater.bat", "w")
        f.write(batFile)
        f.close()
        subprocess.Popen("start updater.bat", shell=True)
        sys.exit(0)

    # Download and replace bin through other process for Linux
    def updateForLinux(url):
        bashFile = (
            """#!/bin/bash
echo ""
echo "[+] Starting Screeni-py updater, Please Wait..."
sleep 3
echo "[+] Screenipy Software Updater!"
echo "[+] Downloading Software Update..."
echo "[+] This may take some time as per your Internet Speed, Please Wait..."
wget -q """
            + url
            + """ -O screenipy.bin
echo "[+] Newly downloaded file saved in $(pwd)"
chmod +x screenipy.bin
echo "[+] Update Completed! Run 'screenipy.bin' again as usual to continue.."
rm updater.sh
        """
        )
        f = open("updater.sh", "w")
        f.write(bashFile)
        f.close()
        subprocess.Popen("bash updater.sh", shell=True)
        sys.exit(0)

        # Download and replace run through other process for Mac

    def updateForMac(url):
        bashFile = (
            """#!/bin/bash
echo ""
echo "[+] Starting Screeni-py updater, Please Wait..."
sleep 3
echo "[+] Screenipy Software Updater!"
echo "[+] Downloading Software Update..."
echo "[+] This may take some time as per your Internet Speed, Please Wait..."
curl -o screenipy.run -L """
            + url
            + """
echo "[+] Newly downloaded file saved in $(pwd)"
chmod +x screenipy.run
echo "[+] Update Completed! Run 'screenipy.run' again as usual to continue.."
rm updater.sh
        """
        )
        f = open("updater.sh", "w")
        f.write(bashFile)
        f.close()
        subprocess.Popen("bash updater.sh", shell=True)
        sys.exit(0)

    # Parse changelog from release.md
    def showWhatsNew():
        url = "https://raw.githubusercontent.com/pranjal-joshi/Screeni-py/main/src/release.md"
        md = requests.get(url)
        txt = md.text
        txt = txt.split("New?")[1]
        # txt = txt.split("## Downloads")[0]
        txt = txt.split("## Installation Guide")[0]
        txt = txt.replace("**", "").replace("`", "").strip()
        return txt + "\n"

    @staticmethod
    def _parse_version(v: str):
        """Parse a semver string like '3.0.1' or 'v3.0.1' into a comparable tuple."""
        return tuple(int(x) for x in v.lstrip("v").split("."))

    # Check for update and download if available
    def checkForUpdate(proxyServer, VERSION="1.0"):
        OTAUpdater.checkForUpdate.url = None
        guiUpdateMessage = ""
        try:
            resp = None
            now = OtaUpdater._parse_version(VERSION)
            if proxyServer:
                resp = requests.get(
                    "https://api.github.com/repos/pranjal-joshi/Screeni-py/releases/latest",
                    proxies={"https": proxyServer},
                    timeout=10,
                )
            else:
                resp = requests.get(
                    "https://api.github.com/repos/pranjal-joshi/Screeni-py/releases/latest",
                    timeout=10,
                )
            # Disabling Exe check as Executables are deprecated v2.03 onwards
            """
            if 'Windows' in platform.system():
                OTAUpdater.checkForUpdate.url = resp.json()['assets'][1]['browser_download_url']
                size = int(resp.json()['assets'][1]['size']/(1024*1024))
            elif 'Darwin' in platform.system():
                OTAUpdater.checkForUpdate.url = resp.json()['assets'][2]['browser_download_url']
                size = int(resp.json()['assets'][2]['size']/(1024*1024))
            else:
                OTAUpdater.checkForUpdate.url = resp.json()['assets'][0]['browser_download_url']
                size = int(resp.json()['assets'][0]['size']/(1024*1024))
            # if(float(resp.json()['tag_name']) > now):
            if(float(resp.json()['tag_name']) > now and not isDocker()):    # OTA not applicable if we're running in docker!
                print(colorText.BOLD + colorText.WARN + "[+] What's New in this Update?\n" + OTAUpdater.showWhatsNew() + colorText.END)
                action = str(input(colorText.BOLD + colorText.WARN + ('\n[+] New Software update (v%s) available. Download Now (Size: %dMB)? [Y/N]: ' % (str(resp.json()['tag_name']),size)))).lower()
                if(action == 'y'):
                    try:
                        if 'Windows' in platform.system():
                            OTAUpdater.updateForWindows(OTAUpdater.checkForUpdate.url)
                        elif 'Darwin' in platform.system():
                            OTAUpdater.updateForMac(OTAUpdater.checkForUpdate.url)
                        else:
                            OTAUpdater.updateForLinux(OTAUpdater.checkForUpdate.url)
                    except Exception as e:
                        print(colorText.BOLD + colorText.WARN + '[+] Error occured while updating!' + colorText.END)
                        raise(e)
            """
            _tag = OtaUpdater._parse_version(resp.json()["tag_name"])
            if _tag > now and not isDocker():
                print(
                    colorText.BOLD
                    + colorText.FAIL
                    + "[+] Executables are now DEPRECATED!\nFollow instructions given at https://github.com/pranjal-joshi/Screeni-py to switch to Docker.\n"
                    + colorText.END
                )
            elif _tag > now and isDocker():  # OTA not applicable if we're running in docker!
                print(
                    colorText.BOLD
                    + colorText.FAIL
                    + (
                        "\n[+] New Software update (v{}) available.\n[+] Run `docker pull joshipranjal/screeni-py:latest` to update your docker to the latest version!\n".format(
                            str(resp.json()["tag_name"])
                        )
                    )
                    + colorText.END
                )
                print(
                    colorText.BOLD
                    + colorText.WARN
                    + "[+] What's New in this Update?\n"
                    + OTAUpdater.showWhatsNew()
                    + colorText.END
                )
                if isGui():
                    guiUpdateMessage = f"New Software update (v{resp.json()['tag_name']}) available - Watch this [**YouTube Video**](https://youtu.be/T41m13iMyJc) for additional help or Update by running following command:\n\n**`docker pull joshipranjal/screeni-py:latest`**"
            elif _tag < now:
                print(
                    colorText.BOLD
                    + colorText.FAIL
                    + (f"[+] This version (v{VERSION}) is in Development mode and unreleased!")
                    + colorText.END
                )
                if isGui():
                    guiUpdateMessage = (
                        f"This version (v{VERSION}) is in Development mode and unreleased!"
                    )
                return OTAUpdater.developmentVersion, guiUpdateMessage
        except Exception as e:
            print(
                colorText.BOLD
                + colorText.FAIL
                + "[+] Failure while checking update!"
                + colorText.END
            )
            print(e)
            if OTAUpdater.checkForUpdate.url is not None:
                print(
                    colorText.BOLD
                    + colorText.BLUE
                    + (f"[+] Download update manually from {OTAUpdater.checkForUpdate.url}\n")
                    + colorText.END
                )
        return None, guiUpdateMessage
