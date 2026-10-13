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
    The MIT License (MIT)

    Copyright (c) 2023 pkjmesra

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

"""
import os
import sys
from enum import Enum
from time import sleep

from PKDevTools.classes import Archiver
from PKDevTools.classes.ColorText import colorText
from PKDevTools.classes.Environment import PKEnvironment
from PKDevTools.classes.log import default_logger
from PKDevTools.classes.OutputControls import OutputControls
from PKDevTools.classes.Pikey import PKPikey
from PKDevTools.classes.Singleton import SingletonMixin, SingletonType
from pkscreener.classes import ConsoleUtility, Utility
from pkscreener.classes.ConfigManager import parser, tools
from pkscreener.classes.MenuOptions import menus
from pkscreener.classes.PKAnalytics import PKAnalyticsService, track_all


class ValidationResult(Enum):
    Success = 0
    BadUserID = 1
    BadOTP = 2
    Trial = 3
    UserDoesNotExist = 4


class PKUserRegistration(SingletonMixin, metaclass=SingletonType):
    def __init__(self):
        super().__init__()
        self._userID = 0
        self._otp = 0

    @classmethod
    def populateSavedUserCreds(self):
        configManager = tools()
        configManager.getConfig(parser)
        PKUserRegistration().userID = configManager.userID
        PKUserRegistration().otp = configManager.otp

    @classmethod
    def resetSavedUserCreds(self):
        return
        configManager = tools()
        configManager.getConfig(parser)
        PKUserRegistration().userID = ""
        PKUserRegistration().otp = ""
        configManager.otp = ""
        configManager.userID = ""
        configManager.setConfig(parser, default=True, showFileCreatedText=False)

    @classmethod
    def savedUserCreds(self):
        configManager = tools()
        configManager.getConfig(parser)
        configManager.userID = str(PKUserRegistration().userID)
        configManager.otp = str(PKUserRegistration().otp)
        configManager.setConfig(parser, default=True, showFileCreatedText=False)

    @property
    def userID(self):
        return self._userID

    @userID.setter
    def userID(self, newuserID):
        self._userID = newuserID

    @property
    def otp(self):
        return self._otp

    @otp.setter
    def otp(self, newotp):
        self._otp = newotp

    @classmethod
    def validateToken(self, retrialCount=0):
        try:
            if "RUNNER" in os.environ or (
                "USER_ID" in os.environ
                and os.environ["USER_ID"] == str(PKUserRegistration().userID)
            ):
                return True, ValidationResult.Success
            # Clear any cached responses for this user
            import requests_cache

            requests_cache.clear()
            # Also clear the fetcher's session cache
            from PKDevTools.classes.Fetcher import session

            session.cache.clear()
            PKPikey.removeSavedFile(f"{PKUserRegistration().userID}")
            max_retries = 5
            for retry in range(max_retries):
                resp = Utility.tools.tryFetchFromServer(
                    cache_file=f"{PKUserRegistration().userID}.pdf",
                    directory="results/Data",
                    hideOutput=False,
                    branchName="refs/heads/SubData",
                    no_cache=True,
                )
                if resp is not None and resp.status_code == 200:
                    # success
                    break
                if retry < max_retries - 1:
                    sleep(2 * (retry + 1))  # exponential backoff
            else:
                # all retries failed
                if resp is not None and resp.status_code != 200:
                    PKAnalyticsService().track_error(
                        error_type="validateTokenError",
                        error_message=f"Invalid Response for user {PKUserRegistration().userID}, status: {resp.status_code if resp else 'None'}",
                        context="PKUserRegistration.validateToken:ValidationResult.BadUserID",
                    )
                    if resp is not None and resp.status_code == 404:
                        PKUserRegistration.resetSavedUserCreds()
                        return False, ValidationResult.UserDoesNotExist
                    if retrialCount <= 3:
                        sleep(2)
                        return PKUserRegistration.validateToken(retrialCount=retrialCount + 1)
                    PKUserRegistration.resetSavedUserCreds()
                    return False, ValidationResult.BadUserID
            with open(
                os.path.join(Archiver.get_user_data_dir(), f"{PKUserRegistration().userID}.pdf"),
                "wb",
            ) as f:
                f.write(resp.content)
            if not PKPikey.openFile(f"{PKUserRegistration().userID}.pdf", PKUserRegistration().otp):
                PKAnalyticsService().track_error(
                    error_type="validateTokenError",
                    error_message=f"Invalid OTP for user {PKUserRegistration().userID}",
                    context=f"PKUserRegistration.validateToken:ValidationResult.BadOTP:{PKUserRegistration().userID}",
                )
                # if retrialCount <= 3:
                #     sleep(2)
                #     return PKUserRegistration.validateToken(retrialCount=retrialCount+1)
                # PKUserRegistration.resetSavedUserCreds()
                # return False, ValidationResult.BadOTP

            PKUserRegistration.savedUserCreds()
            os.environ["USER_ID"] = str(PKUserRegistration().userID)
            return True, ValidationResult.Success
        except Exception as e:  # pragma: no cover
            if "RUNNER" in os.environ:
                return True, ValidationResult.Success
            PKAnalyticsService().track_error(
                error_type="validateTokenError",
                error_message=str(e),
                context=f"PKUserRegistration.validateToken:ValidationResult.BadOTP:{PKUserRegistration().userID}",
            )
            if retrialCount < 2:
                sleep(2)
                return PKUserRegistration.validateToken(retrialCount=retrialCount + 1)
            PKUserRegistration.resetSavedUserCreds()
            return False, ValidationResult.BadOTP

    @classmethod
    @track_all("PKUserRegistration_login")
    def login(self, trialCount=0):
        try:
            configManager = tools()
            configManager.getConfig(parser)
            PKAnalyticsService().collectMetrics(
                user=configManager.userID
                if configManager.userID is not None and len(configManager.userID) > 0
                else None,
                async_mode=True,
            )
            if "RUNNER" in os.environ:
                return ValidationResult.Success
        except Exception as e:  # pragma: no cover
            PKAnalyticsService().track_error(
                error_type="UserLoginError",
                error_message=str(e),
                context="PKUserRegistration.login:ValidationResult.BadUserID",
            )
            return ValidationResult.BadUserID
        ConsoleUtility.PKConsoleTools.clearScreen(userArgs=None, clearAlways=True, forceTop=True)
        if configManager.userID is not None and len(configManager.userID) > 0:
            PKUserRegistration.populateSavedUserCreds()
            if PKUserRegistration.validateToken()[0]:
                return ValidationResult.Success
            else:
                PKUserRegistration.resetSavedUserCreds()
        if trialCount >= 1:
            return PKUserRegistration.presentTrialOptions()

        is_subscription_enabled = bool(int(PKEnvironment().SUBSCRIPTION_ENABLED))
        premiumHelpText = (
            f"\n[+] {colorText.FAIL}PKScreener does offer certain premium/paid features!{colorText.END}"
            if is_subscription_enabled
            else ""
        )
        OutputControls().printOutput(
            f"[+] {colorText.GREEN}PKScreener will always remain free and open source!{colorText.END}{premiumHelpText}\n[+] {colorText.GREEN}Please use {colorText.END}{colorText.WARN}@nse_pkscreener_bot{colorText.END}{colorText.GREEN} in telegram app on \n    your mobile phone to request your {colorText.END}{colorText.WARN}userID{colorText.END}{colorText.GREEN} and {colorText.END}{colorText.WARN}OTP{colorText.END}{colorText.GREEN} to login:\n{colorText.END}"
        )
        username = None
        if configManager.userID is not None and len(configManager.userID) >= 1:
            username = (
                OutputControls().takeUserInput(
                    f"[+] Your UserID from telegram: (Default: {colorText.GREEN}{configManager.userID}{colorText.END}): ",
                    enableUserInput=True,
                )
                or configManager.userID
            )
        else:
            username = OutputControls().takeUserInput(
                f"[+] {colorText.GREEN}Your UserID from telegram: {colorText.END}",
                enableUserInput=True,
            )
        if username is None or not username or len(username.strip()) <= 0:
            OutputControls().printOutput(
                f"{colorText.WARN}[+] We urge you to register on telegram (/OTP on @nse_pkscreener_bot) and then login to use PKScreener!{colorText.END}\n"
            )
            OutputControls().printOutput(
                f"{colorText.FAIL}[+] Invalid userID!{colorText.END}\n{colorText.WARN}[+] Maybe try entering the {colorText.END}{colorText.GREEN}UserID{colorText.END}{colorText.WARN} instead of username?{colorText.END}\n[+] {colorText.WARN}If you have purchased a subscription and are still not able to login, please reach out to {colorText.END}{colorText.GREEN}@ItsOnlyPK{colorText.END} {colorText.WARN}on Telegram!{colorText.END}\n[+] {colorText.FAIL}Please try again or press Ctrl+C to exit!{colorText.END}"
            )
            return PKUserRegistration.presentTrialOptions()
        otp = (
            OutputControls().takeUserInput(
                f"[+] {colorText.WARN}OTP received on telegram from {colorText.END}{colorText.GREEN}@nse_pkscreener_bot (Use command /otp to get OTP): {colorText.END}",
                enableUserInput=True,
            )
            or configManager.otp
        )
        invalidOTP = False
        try:
            int(otp)
        except KeyboardInterrupt:  # pragma: no cover
            raise KeyboardInterrupt
        except Exception as e:  # pragma: no cover
            default_logger().debug(e, exc_info=True)
            invalidOTP = True
            pass
        if otp is None or len(str(otp)) <= 0:
            OutputControls().printOutput(
                f"{colorText.WARN}[+] We urge you to register on telegram (/OTP on @nse_pkscreener_bot) and then login to use PKScreener!{colorText.END}\n"
            )
            OutputControls().printOutput(
                f"{colorText.FAIL}[+] Invalid userID/OTP!{colorText.END}\n{colorText.WARN}[+] Maybe try entering the {colorText.END}{colorText.GREEN}UserID{colorText.END}{colorText.WARN} instead of username?{colorText.END}\n[+] {colorText.WARN}If you have purchased a subscription and are still not able to login, please reach out to {colorText.END}{colorText.GREEN}@ItsOnlyPK{colorText.END} {colorText.WARN}on Telegram!{colorText.END}\n[+] {colorText.FAIL}Please try again or press Ctrl+C to exit!{colorText.END}"
            )
            return PKUserRegistration.presentTrialOptions()

        if len(str(otp)) <= 5 or invalidOTP:
            OutputControls().printOutput(
                f"{colorText.WARN}[+] Please enter a valid OTP!{colorText.END}\n[+] {colorText.FAIL}Please try again or press Ctrl+C to exit!{colorText.END}"
            )
            sleep(3)
            return PKUserRegistration.login()
        try:
            userUsedUserID = False
            try:
                usernameInt = int(username)
                userUsedUserID = True
            except:  # pragma: no cover
                userUsedUserID = False
                pass
            if userUsedUserID:
                OutputControls().printOutput(
                    f"{colorText.GREEN}[+] Please wait!{colorText.END}\n[+] {colorText.WARN}Validating the OTP. You can press Ctrl+C to exit!{colorText.END}"
                )
                PKUserRegistration().userID = usernameInt
                PKUserRegistration().otp = otp
                PKUserRegistration.savedUserCreds()
                if trialCount == 1:
                    # For some reason, at times, the first validation attempt
                    # after entering correct credentials fails due to some
                    # caching issue. So we can add a retry with some
                    # delay before it is marked as failed.
                    sleep(10)
                validationResult, validationReason = PKUserRegistration.validateToken()
                if not validationResult and validationReason == ValidationResult.userDoesNotExist:
                    OutputControls().printOutput(
                        f"{colorText.FAIL}[+] Server busy!{colorText.END}\n{colorText.WARN}[+] Maybe try entering the {colorText.END}{colorText.GREEN}UserID{colorText.END} and {colorText.GREEN}OTP{colorText.END} after a few seconds!\n[+] {colorText.WARN}If you have purchased a subscription and are still not able to login, please reach out to {colorText.END}{colorText.GREEN}@ItsOnlyPK{colorText.END} {colorText.WARN}on Telegram!{colorText.END}\n[+] {colorText.FAIL}Please try again or press Ctrl+C to exit!{colorText.END}"
                    )
                    sleep(5)
                    return PKUserRegistration.login(trialCount=trialCount + 1)
                if not validationResult and validationReason == ValidationResult.BadUserID:
                    PKUserRegistration.resetSavedUserCreds()
                    OutputControls().printOutput(
                        f"{colorText.FAIL}[+] Invalid userID!{colorText.END}\n{colorText.WARN}[+] Maybe try entering the {colorText.END}{colorText.GREEN}UserID{colorText.END}{colorText.WARN} instead of username?{colorText.END}\n[+] {colorText.WARN}If you have purchased a subscription and are still not able to login, please reach out to {colorText.END}{colorText.GREEN}@ItsOnlyPK{colorText.END} {colorText.WARN}on Telegram!{colorText.END}\n[+] {colorText.FAIL}Please try again or press Ctrl+C to exit!{colorText.END}"
                    )
                    return PKUserRegistration.presentTrialOptions()
                if not validationResult and validationReason == ValidationResult.BadOTP:
                    PKUserRegistration.resetSavedUserCreds()
                    OutputControls().printOutput(
                        f"{colorText.FAIL}[+] Invalid OTP!{colorText.END}\n[+] {colorText.GREEN}If you have purchased a subscription and are still not able to login, please reach out to @ItsOnlyPK on Telegram!{colorText.END}\n[+] {colorText.FAIL}Please try again or press Ctrl+C to exit!{colorText.END}"
                    )
                    sleep(5)
                    return PKUserRegistration.login(trialCount=trialCount + 1)
                if validationResult and validationReason == ValidationResult.Success:
                    # Remember the userID for future login
                    configManager.userID = str(PKUserRegistration().userID)
                    configManager.otp = str(PKUserRegistration().otp)
                    configManager.setConfig(parser, default=True, showFileCreatedText=False)
                    ConsoleUtility.PKConsoleTools.clearScreen(
                        userArgs=None, clearAlways=True, forceTop=True
                    )
                    return validationReason
        except KeyboardInterrupt:  # pragma: no cover
            raise KeyboardInterrupt
        except Exception as e:  # pragma: n`o cover
            default_logger().debug(e, exc_info=True)
            pass
        PKUserRegistration.resetSavedUserCreds()
        OutputControls().printOutput(
            f"{colorText.WARN}[+] Invalid userID or OTP!{colorText.END}\n{colorText.GREEN}[+] May be try entering the {'UserID instead of username?' if userUsedUserID else 'Username instead of userID?'} {colorText.END}\n[+] {colorText.FAIL}Please try again or press Ctrl+C to exit!{colorText.END}"
        )
        sleep(3)
        return PKUserRegistration.login(trialCount=trialCount + 1)

    @classmethod
    def presentTrialOptions(self):
        m = menus()
        multilineOutputEnabled = OutputControls().enableMultipleLineOutput
        OutputControls().enableMultipleLineOutput = True
        m.renderUserType()
        userTypeOption = OutputControls().takeUserInput(
            colorText.FAIL + "  [+] Select option: ", enableUserInput=True, defaultInput="1"
        )
        OutputControls().enableMultipleLineOutput = multilineOutputEnabled
        if str(userTypeOption).upper() in ["1"]:
            PKUserRegistration.resetSavedUserCreds()
            return PKUserRegistration.login(trialCount=0)
        elif str(userTypeOption).upper() in ["2"]:
            return ValidationResult.Trial
        sys.exit(0)
