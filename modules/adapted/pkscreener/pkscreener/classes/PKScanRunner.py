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
import multiprocessing
import os
import sys
import time
from time import sleep

import pandas as pd
import pkscreener.classes.Fetcher as Fetcher
import pkscreener.classes.ScreeningStatistics as ScreeningStatistics
from PKDevTools.classes import Archiver
from PKDevTools.classes.ColorText import colorText
from PKDevTools.classes.FunctionTimeouts import exit_after
from PKDevTools.classes.log import default_logger
from PKDevTools.classes.multiprocessing_logging import LogQueueReader
from PKDevTools.classes.OutputControls import OutputControls
from PKDevTools.classes.PKDateUtilities import PKDateUtilities
from PKDevTools.classes.PKGitFolderDownloader import downloadFolder
from PKDevTools.classes.PKHalo import PKHalo
from PKDevTools.classes.PKMultiProcessorClient import PKMultiProcessorClient
from PKDevTools.classes.SuppressOutput import SuppressOutput
from pkscreener.classes import AssetsManager
from pkscreener.classes.CandlePatterns import CandlePatterns
from pkscreener.classes.ConfigManager import parser, tools
from pkscreener.classes.PKAnalytics import AnalyticsCategory, track_event, track_performance
from pkscreener.classes.StockScreener import StockScreener


class PKScanRunner:
    configManager = tools()
    configManager.getConfig(parser)
    fetcher = Fetcher.screenerStockDataFetcher(configManager)
    candlePatterns = CandlePatterns()
    tasks_queue = None
    results_queue = None
    scr = None
    consumers = None

    # New static variables for reuse across scans
    _cached_consumers = None
    _cached_tasks_queue = None
    _cached_results_queue = None
    _cached_logging_queue = None
    _cached_log_queue_reader = None

    @staticmethod
    def cleanup():
        """Terminate all workers if they exist. Safe to call multiple times."""
        if PKScanRunner._cached_consumers is not None:
            # We don't have userPassedArgs here; we can pass None or use defaults.
            # Modify terminateAllWorkers to handle None gracefully.
            PKScanRunner.terminateAllWorkers(
                userPassedArgs=None,
                consumers=PKScanRunner._cached_consumers,
                tasks_queue=PKScanRunner._cached_tasks_queue,
                testing=False,
            )
            PKScanRunner._cached_consumers = None
            PKScanRunner._cached_tasks_queue = None
            PKScanRunner._cached_results_queue = None

    @staticmethod
    def initDataframes():
        """
        Initialize empty DataFrames for screening results and save results.

        Returns:
            tuple: (screenResults, saveResults) - Two empty DataFrames with predefined columns
        """
        screenResults = pd.DataFrame(
            columns=[
                "Stock",
                "Consol.",
                "Breakout",
                "LTP",
                "52Wk-H",
                "52Wk-L",
                "%Chng",
                "volume",
                "MA-Signal",
                "RSI",
                "RSIi",
                "Trend",
                "Pattern",
                "CCI",
            ]
        )
        saveResults = pd.DataFrame(
            columns=[
                "Stock",
                "Consol.",
                "Breakout",
                "LTP",
                "52Wk-H",
                "52Wk-L",
                "%Chng",
                "volume",
                "MA-Signal",
                "RSI",
                "RSIi",
                "Trend",
                "Pattern",
                "CCI",
            ]
        )
        return screenResults, saveResults

    @staticmethod
    @track_performance("PKScanRunner_initQueues")
    def initQueues(minimumCount=0, userPassedArgs=None):
        """
        Initialize multiprocessing queues with optimized consumer count.

        This method creates task, result, and logging queues for multiprocessing.
        It also determines the optimal number of consumer processes based on
        the workload type and system capabilities.

        Args:
            minimumCount (int): Minimum number of items to process
            userPassedArgs: User arguments containing configuration options

        Returns:
            tuple: (tasks_queue, results_queue, totalConsumers, logging_queue)
        """
        tasks_queue = multiprocessing.JoinableQueue()
        results_queue = multiprocessing.Queue()
        logging_queue = multiprocessing.Queue()
        cpu_count = multiprocessing.cpu_count()
        # OPTIMIZATION: For specific stock scans with known stockCodes, use fewer consumers
        # Process creation overhead is significant; fewer consumers = faster startup
        if userPassedArgs and getattr(userPassedArgs, "stocklist", None):
            # For specific stock lists, use 3 consumers maximum (balanced for performance)
            totalConsumers = min(3, multiprocessing.cpu_count())
            default_logger().debug(f"Using {totalConsumers} consumers for specific stock list")
        elif (
            userPassedArgs
            and userPassedArgs.options
            and userPassedArgs.options.split(":")[1] == "0"
        ):
            # For individual stock analysis, use single consumer (no parallel overhead needed)
            totalConsumers = 1
            default_logger().debug("Using single consumer for individual stock analysis")
        else:
            totalConsumers = (
                1
                if (userPassedArgs is not None and userPassedArgs.singlethread)
                else min(minimumCount, multiprocessing.cpu_count())
            )
            if totalConsumers == 1:
                totalConsumers = 2  # This is required for single core machine

        # OPTIMIZATION: Cap consumers to 4 for better startup time
        # Process creation overhead increases significantly with more consumers
        # On Mac, creating more than 4 processes takes ~2s each
        # On Windows/Linux, similar overhead exists but slightly less
        max_consumers = (
            max(3, cpu_count // 2)
            if sys.platform.startswith("win")
            else (max(4, int(cpu_count * 0.5)) if sys.platform.startswith("darwin") else cpu_count)
        )
        if totalConsumers > max_consumers:
            default_logger().debug(
                f"Capping consumers from {totalConsumers} to {max_consumers} for faster startup"
            )
            totalConsumers = max_consumers

        return tasks_queue, results_queue, totalConsumers, logging_queue

    @staticmethod
    def populateQueues(items, tasks_queue, exit=False, userPassedArgs=None):
        """
        Populate the task queue with items to process.

        Args:
            items (list): List of items to add to the queue
            tasks_queue (multiprocessing.Queue): Queue to populate
            exit (bool): Whether to add exit signals for processes
            userPassedArgs: User arguments for piped scan detection
        """
        # default_logger().debug(f"Unfinished items in task_queue: {tasks_queue.qsize()}")
        for item in items:
            tasks_queue.put(item)
        mayBePiped = userPassedArgs is not None and (
            userPassedArgs.monitor is not None or "|" in userPassedArgs.options
        )
        if exit and not mayBePiped:
            # Append exit signal for each process indicated by None
            for _ in range(multiprocessing.cpu_count()):
                tasks_queue.put(None)

    @staticmethod
    def getScanDurationParameters(testing, menuOption):
        """
        Calculate the duration parameters for scanning or backtesting.

        Args:
            testing (bool): Whether in testing mode
            menuOption (str): Selected menu option ('B' for backtest, others for scan)

        Returns:
            tuple: (samplingDuration, fillerPlaceHolder, actualHistoricalDuration)
                   - samplingDuration: Total periods to sample
                   - fillerPlaceHolder: Offset for filler data
                   - actualHistoricalDuration: Actual historical periods to process
        """
        # Number of days from past, including the backtest duration chosen by the user
        # that we will need to consider to evaluate the data. If the user choses 10-period
        # backtesting, we will need to have the past 6-months or whatever is returned by
        # x = getHistoricalDays and 10 days of recent data. So total rows to consider
        # will be x + 10 days.
        samplingDuration = (
            (3 if testing else PKScanRunner.configManager.backtestPeriod + 1)
            if menuOption.upper() in ["B"]
            else 2
        )
        fillerPlaceHolder = 1 if menuOption in ["B"] else 2
        actualHistoricalDuration = samplingDuration - fillerPlaceHolder
        return samplingDuration, fillerPlaceHolder, actualHistoricalDuration

    @staticmethod
    def addScansWithDefaultParams(
        userArgs,
        testing,
        testBuild,
        newlyListedOnly,
        downloadOnly,
        backtestPeriod,
        listStockCodes,
        menuOption,
        exchangeName,
        executeOption,
        volumeRatio,
        items,
        daysInPast,
        runOption="",
    ):
        """
        Add scan items with default parameters from defaults.json configuration.

        This method reads default parameters from defaults.json and creates scan
        items for each configured option.

        Args:
            userArgs: User command line arguments
            testing (bool): Whether in testing mode
            testBuild (bool): Whether this is a test build
            newlyListedOnly (bool): Whether to only scan newly listed stocks
            downloadOnly (bool): Whether only downloading data
            backtestPeriod (int): Backtest period in days
            listStockCodes (list): List of stock codes to scan
            menuOption (str): Selected menu option
            exchangeName (str): Exchange name (INDIA, NASDAQ)
            executeOption (int): Execute option number
            volumeRatio (float): Volume ratio for filtering
            items (list): Existing items list to extend
            daysInPast (int): Number of days in past for historical data
            runOption (str): Run option string for identification

        Returns:
            list: Updated items list with added scan items
        """
        import json

        defaultOptionsDict = {}
        filePath = os.path.join(Archiver.get_user_data_dir(), "defaults.json")
        if not os.path.exists(filePath):
            AssetsManager.PKAssetsManager.downloadSavedDefaultsFromServer("defaults.json")
        if not os.path.exists(filePath):
            return items
        with open(filePath) as f:
            defaultOptionsDict = json.loads(f.read())
        for scanOption in defaultOptionsDict:
            items = PKScanRunner.addStocksToItemList(
                userArgs=userArgs,
                testing=testing,
                testBuild=testBuild,
                newlyListedOnly=newlyListedOnly,
                downloadOnly=downloadOnly,
                minRSI=defaultOptionsDict[scanOption]["minRSI"],
                maxRSI=defaultOptionsDict[scanOption]["maxRSI"],
                insideBarToLookback=defaultOptionsDict[scanOption]["insideBarToLookback"],
                respChartPattern=defaultOptionsDict[scanOption]["respChartPattern"],
                daysForLowestVolume=defaultOptionsDict[scanOption]["daysForLowestVolume"],
                backtestPeriod=backtestPeriod,
                reversalOption=defaultOptionsDict[scanOption]["reversalOption"],
                maLength=defaultOptionsDict[scanOption]["maLength"],
                listStockCodes=listStockCodes,
                menuOption=menuOption,
                exchangeName=exchangeName,
                executeOption=int(scanOption.split(":")[2]),
                volumeRatio=volumeRatio,
                items=items,
                daysInPast=daysInPast,
                runOption=scanOption,
            )
        return items

    @staticmethod
    def addStocksToItemList(
        userArgs,
        testing,
        testBuild,
        newlyListedOnly,
        downloadOnly,
        minRSI,
        maxRSI,
        insideBarToLookback,
        respChartPattern,
        daysForLowestVolume,
        backtestPeriod,
        reversalOption,
        maLength,
        listStockCodes,
        menuOption,
        exchangeName,
        executeOption,
        volumeRatio,
        items,
        daysInPast,
        runOption="",
    ):
        """
        Add individual stock items to the processing list.

        This method creates a tuple of parameters for each stock and adds it to the items list.

        Args:
            userArgs: User command line arguments
            testing (bool): Whether in testing mode
            testBuild (bool): Whether this is a test build
            newlyListedOnly (bool): Whether to only scan newly listed stocks
            downloadOnly (bool): Whether only downloading data
            minRSI (int): Minimum RSI value for filtering
            maxRSI (int): Maximum RSI value for filtering
            insideBarToLookback (int): Number of days to look back for inside bar pattern
            respChartPattern (int): Chart pattern response option
            daysForLowestVolume (int): Days to consider for lowest volume calculation
            backtestPeriod (int): Backtest period in days
            reversalOption (int): Reversal option for pattern detection
            maLength (int): Moving average length parameter
            listStockCodes (list): List of stock codes to process
            menuOption (str): Selected menu option
            exchangeName (str): Exchange name
            executeOption (int): Execute option number
            volumeRatio (float): Volume ratio for filtering
            items (list): Existing items list to extend
            daysInPast (int): Number of days in past for historical data
            runOption (str): Run option string for identification

        Returns:
            list: Updated items list with added stock items
        """
        moreItems = [
            (
                runOption,
                menuOption,
                exchangeName,
                executeOption,
                reversalOption,
                maLength,
                daysForLowestVolume,
                minRSI,
                maxRSI,
                respChartPattern,
                insideBarToLookback,
                len(listStockCodes),
                PKScanRunner.configManager.cacheEnabled,
                stock,
                newlyListedOnly,
                downloadOnly,
                volumeRatio,
                testBuild,
                userArgs,
                daysInPast,
                (
                    backtestPeriod
                    if menuOption == "B"
                    else PKScanRunner.configManager.effectiveDaysToLookback
                ),
                default_logger().level,
                (menuOption in ["B", "G", "X", "S", "C", "F"])
                or (userArgs.backtestdaysago is not None),
                # assumption is that fetcher.fetchStockData would be
                # mocked to avoid calling yf.download again and again
                PKScanRunner.fetcher.fetchStockData() if testing else None,
            )
            for stock in listStockCodes
        ]
        items.extend(moreItems)
        return items

    @staticmethod
    def getStocksListForScan(
        userArgs, menuOption, totalStocksInReview, downloadedRecently, daysInPast
    ):
        """
        Retrieve the list of stocks to scan from saved results or fetch fresh.

        Args:
            userArgs: User command line arguments
            menuOption (str): Selected menu option
            totalStocksInReview (int): Running total of stocks under review
            downloadedRecently (bool): Whether data was downloaded recently
            daysInPast (int): Number of days in past for historical data

        Returns:
            tuple: (listStockCodes, savedStocksCount, pastDate)
                   - listStockCodes: List of stock codes to scan
                   - savedStocksCount: Number of stocks from saved results
                   - pastDate: Date string for past results
        """
        savedStocksCount = 0
        pastDate, savedListResp = PKScanRunner.downloadSavedResults(
            daysInPast, downloadedRecently=downloadedRecently
        )
        downloadedRecently = True
        if savedListResp is not None and len(savedListResp) > 0:
            savedListStockCodes = savedListResp
            savedStocksCount = len(savedListStockCodes)
            if savedStocksCount > 0:
                listStockCodes = savedListStockCodes
                totalStocksInReview += savedStocksCount
            else:
                if menuOption in ["B"] and not userArgs.forceBacktestsForZeroResultDays:
                    # We have a zero length result saved in repo.
                    # Likely we didn't have any stock in the result output. So why run the scan again?
                    listStockCodes = savedListStockCodes
                totalStocksInReview += len(listStockCodes)
        else:
            totalStocksInReview += len(listStockCodes)
        return listStockCodes, savedStocksCount, pastDate

    @staticmethod
    def getBacktestDaysForScan(userArgs, backtestPeriod, menuOption, actualHistoricalDuration):
        """
        Calculate the number of days in the past for backtest or scan.

        Args:
            userArgs: User command line arguments
            backtestPeriod (int): Backtest period in days
            menuOption (str): Selected menu option
            actualHistoricalDuration (int): Actual historical duration to consider

        Returns:
            int: Number of days in the past for data retrieval
        """
        daysInPast = (
            actualHistoricalDuration
            if (menuOption == "B")
            else (
                (backtestPeriod)
                if (menuOption == "G")
                else (0 if (userArgs.backtestdaysago is None) else (int(userArgs.backtestdaysago)))
            )
        )

        return daysInPast

    @staticmethod
    def downloadSavedResults(daysInPast, downloadedRecently=False):
        """
        Download saved scan results from GitHub for the given past date.

        Args:
            daysInPast (int): Number of days in the past
            downloadedRecently (bool): Whether results were downloaded recently

        Returns:
            tuple: (pastDate, savedList)
                   - pastDate: Formatted date string
                   - savedList: List of stock codes from saved results
        """
        pastDate = PKDateUtilities.nthPastTradingDateStringFromFutureDate(daysInPast)
        filePrefix = (
            PKScanRunner.getFormattedChoices().replace("B", "X").replace("G", "X").replace("S", "X")
        )
        # url = f"https://raw.github.com/pkjmesra/PKScreener/actions-data-download/actions-data-scan/{filePrefix}_{pastDate}.txt"
        # savedListResp = fetcher.fetchURL(url)
        localPath = Archiver.get_user_outputs_dir()
        downloadedPath = os.path.join(localPath, "PKScreener", "actions-data-scan")
        if not downloadedRecently:
            downloadedPath = downloadFolder(
                localPath=localPath,
                repoPath="pkjmesra/PKScreener",
                branchName="actions-data-download",
                folderName="actions-data-scan",
            )
        items = []
        savedList = []
        fileName = os.path.join(downloadedPath, f"{filePrefix}_{pastDate}.txt")
        if os.path.isfile(fileName):
            # File already exists.
            with open(fileName) as fe:
                stocks = fe.read()
                items = stocks.replace("\n", "").replace('"', "").split(",")
                savedList = sorted(filter(None, list(set(items))))
        return pastDate, savedList

    @staticmethod
    def getFormattedChoices(userArgs, selectedChoice):
        """
        Format the user's menu choices into a string identifier.

        Args:
            userArgs: User command line arguments
            selectedChoice (dict): Dictionary of selected menu choices

        Returns:
            str: Formatted choices string for identification
        """
        isIntraday = PKScanRunner.configManager.isIntradayConfig() or (
            userArgs.intraday is not None
        )
        choices = ""
        for choice in selectedChoice:
            choiceOption = selectedChoice[choice]
            if len(choiceOption) > 0 and ("," not in choiceOption and "." not in choiceOption):
                if len(choices) > 0:
                    choices = f"{choices}_"
                choices = f"{choices}{choiceOption}"
        if choices.endswith("_"):
            choices = choices[:-1]
        choices = f"{choices}{'_i' if isIntraday else ''}"
        return f"{choices.strip()}{'_IA' if userArgs is not None and userArgs.runintradayanalysis else ''}"

    @staticmethod
    def refreshDatabase(consumers, stockDictPrimary, stockDictSecondary):
        """
        Refresh the database references for all worker processes.

        Args:
            consumers (list): List of worker processes
            stockDictPrimary (dict): Primary stock data dictionary
            stockDictSecondary (dict): Secondary stock data dictionary (intraday)
        """
        for worker in consumers:
            worker.objectDictionaryPrimary = stockDictPrimary
            worker.objectDictionarySecondary = stockDictSecondary
            worker.refreshDatabase = True

    @staticmethod
    @track_performance("PKScanRunner_runScanWithParams")
    def runScanWithParams(
        userPassedArgs,
        keyboardInterruptEvent,
        screenCounter,
        screenResultsCounter,
        stockDictPrimary,
        stockDictSecondary,
        testing,
        backtestPeriod,
        menuOption,
        executeOption,
        samplingDuration,
        items,
        screenResults,
        saveResults,
        backtest_df,
        scanningCb,
        tasks_queue,
        results_queue,
        consumers,
        logging_queue,
    ):
        """
        Execute the scan with the provided parameters using multiprocessing.

        This method orchestrates the entire scanning process, including queue setup,
        worker management, and result collection.

        Args:
            userPassedArgs: User command line arguments
            keyboardInterruptEvent: Event for handling keyboard interrupts
            screenCounter: Shared counter for screen processing
            screenResultsCounter: Shared counter for results processing
            stockDictPrimary (dict): Primary stock data dictionary
            stockDictSecondary (dict): Secondary stock data dictionary
            testing (bool): Whether in testing mode
            backtestPeriod (int): Backtest period in days
            menuOption (str): Selected menu option
            executeOption (int): Execute option number
            samplingDuration (int): Duration for sampling historical data
            items (list): List of items to process
            screenResults (DataFrame): Existing screen results
            saveResults (DataFrame): Existing save results
            backtest_df (DataFrame): Existing backtest DataFrame
            scanningCb (callable): Callback function for scanning
            tasks_queue (multiprocessing.Queue): Task queue
            results_queue (multiprocessing.Queue): Result queue
            consumers (list): List of worker processes
            logging_queue (multiprocessing.Queue): Logging queue

        Returns:
            tuple: (screenResults, saveResults, backtest_df, tasks_queue, results_queue, consumers, logging_queue)
        """
        if tasks_queue is None or results_queue is None or consumers is None:
            tasks_queue, results_queue, consumers, logging_queue = PKScanRunner.prepareToRunScan(
                menuOption,
                keyboardInterruptEvent,
                screenCounter,
                screenResultsCounter,
                stockDictPrimary,
                stockDictSecondary,
                items,
                executeOption,
                userPassedArgs,
            )
            try:
                if logging_queue is None:
                    logging_queue = multiprocessing.Queue()
                    default_logger().warning("logging_queue was None, created new one")
                try:
                    if logging_queue is not None:
                        log_queue_reader = LogQueueReader(logging_queue)
                        log_queue_reader.daemon = True
                        log_queue_reader.start()
                        default_logger().debug("LogQueueReader started successfully")
                    else:
                        default_logger().warning("logging_queue is None, log reader not started")
                except Exception as e:
                    default_logger().error(f"Failed to start LogQueueReader: {e}", exc_info=True)
            except:  # pragma: no cover
                pass

        PKScanRunner.tasks_queue = tasks_queue
        PKScanRunner.results_queue = results_queue
        PKScanRunner.consumers = consumers
        screenResults, saveResults, backtest_df = scanningCb(
            menuOption,
            items,
            PKScanRunner.tasks_queue,
            PKScanRunner.results_queue,
            len(items),
            backtestPeriod,
            samplingDuration - 1,
            PKScanRunner.consumers,
            screenResults,
            saveResults,
            backtest_df,
            testing=testing,
        )

        OutputControls().printOutput(colorText.END)
        PKScanRunner.resetWorkersForNextScan(consumers, tasks_queue, userPassedArgs, testing)
        return (
            screenResults,
            saveResults,
            backtest_df,
            tasks_queue,
            results_queue,
            consumers,
            logging_queue,
        )

    @staticmethod
    def resetWorkersForNextScan(consumers, tasks_queue, userPassedArgs=None, testing=False):
        """Pause and clear workers but keep them alive for next scan."""
        # Don't terminate unless we are exiting the program
        # Only pause and clear internal queues/state
        for worker in consumers:
            worker.paused = True
            worker._clear()

        # Clear the task queue for next scan
        while True:
            try:
                tasks_queue.get_nowait()
            except:
                break

        # Optionally, clear results queue as well (already done in prepareToRunScan)
        # Keep the workers alive – they will be reused next time

    @exit_after(
        180
    )  # Should not remain stuck starting the multiprocessing clients beyond this time
    @track_performance("PKScanRunner_prepareToRunScan")
    @track_event(
        category=AnalyticsCategory.SYSTEM,
        action="scan_trigger",
        label="scan_{menuOption}_12_{executeOption}",
        capture_params=["userPassedArgs", "menuOption", "executeOption"],
        capture_result=False,
        log_args=False,  # Set to True for debugging, False in production
    )
    @PKHalo(text="  [+] Creating multiple processes for faster processing...", spinner="dots")
    def prepareToRunScan(
        menuOption,
        keyboardInterruptEvent,
        screenCounter,
        screenResultsCounter,
        stockDictPrimary,
        stockDictSecondary,
        items,
        executeOption,
        userPassedArgs,
    ):
        """
        Prepare and initialize the multiprocessing environment for scanning.

        This method creates queues, workers, and sets up the multiprocessing infrastructure.
        It now uses optimized consumer counts and parallel worker startup.

        Args:
            menuOption (str): Selected menu option
            keyboardInterruptEvent: Event for handling keyboard interrupts
            screenCounter: Shared counter for screen processing
            screenResultsCounter: Shared counter for results processing
            stockDictPrimary (dict): Primary stock data dictionary
            stockDictSecondary (dict): Secondary stock data dictionary
            items (list): List of items to process
            executeOption (int): Execute option number
            userPassedArgs: User command line arguments

        Returns:
            tuple: (tasks_queue, results_queue, consumers, logging_queue)
        """
        # If we already have living consumers, reuse them
        if PKScanRunner._cached_consumers is not None and all(
            worker.is_alive()
            for worker in PKScanRunner._cached_consumers
            if hasattr(worker, "is_alive")
        ):
            tasks_queue = PKScanRunner._cached_tasks_queue
            results_queue = PKScanRunner._cached_results_queue
            consumers = PKScanRunner._cached_consumers
            logging_queue = PKScanRunner._cached_logging_queue

            # Update worker internal data (stock dictionaries, refresh flag)
            for worker in consumers:
                worker.objectDictionaryPrimary = stockDictPrimary
                worker.objectDictionarySecondary = stockDictSecondary
                worker.refreshDatabase = True  # force refresh of internal data
                worker.paused = False  # ensure they are not paused

            # Clear any leftover results from previous scan
            while not results_queue.empty():
                try:
                    results_queue.get_nowait()
                except:
                    break

            return tasks_queue, results_queue, consumers, logging_queue

        # Otherwise, create new workers (first time only)
        tasks_queue, results_queue, totalConsumers, logging_queue = PKScanRunner.initQueues(
            len(items), userPassedArgs
        )
        scr = ScreeningStatistics.ScreeningStatistics(PKScanRunner.configManager, default_logger())
        exists, cache_file = AssetsManager.PKAssetsManager.afterMarketStockDataExists(
            intraday=PKScanRunner.configManager.isIntradayConfig()
        )
        sec_cache_file = cache_file if "intraday_" in cache_file else f"intraday_{cache_file}"

        # Get RS rating stock value of the index (commented out for performance)
        rs_score_index = -1

        consumers = [
            PKMultiProcessorClient(
                StockScreener().screenStocks,
                tasks_queue,
                results_queue,
                logging_queue,
                screenCounter,
                screenResultsCounter,
                (stockDictPrimary if menuOption not in ["C"] else None),
                (stockDictSecondary if menuOption not in ["C"] else None),
                PKScanRunner.fetcher.proxyServer,
                keyboardInterruptEvent,
                default_logger(),
                PKScanRunner.fetcher,
                PKScanRunner.configManager,
                PKScanRunner.candlePatterns,
                scr,
                (cache_file if (exists and menuOption in ["C"]) else None),
                (sec_cache_file if (exists and menuOption in ["C"]) else None),
                rs_strange_index=rs_score_index,
            )
            for _ in range(totalConsumers)
        ]

        try:
            intradayFetcher = None
            # intradayFetcher = Intra_Day("SBINEQN") # This will initialise the cookies etc.
        except:  # pragma: no cover
            pass
        for consumer in consumers:
            consumer.intradayNSEFetcher = intradayFetcher

        # Start workers in parallel for faster initialization
        PKScanRunner.startWorkersParallel(consumers)
        # Cache them for future reuse
        PKScanRunner._cached_consumers = consumers
        PKScanRunner._cached_tasks_queue = tasks_queue
        PKScanRunner._cached_results_queue = results_queue
        PKScanRunner._cached_logging_queue = logging_queue

        # Start the log reader once
        if logging_queue is not None and PKScanRunner._cached_log_queue_reader is None:
            PKScanRunner._cached_log_queue_reader = LogQueueReader(logging_queue)
            PKScanRunner._cached_log_queue_reader.daemon = True
            PKScanRunner._cached_log_queue_reader.start()
        return tasks_queue, results_queue, consumers, logging_queue

    @staticmethod
    @track_performance("PKScanRunner_startWorkersParallel")
    def startWorkersParallel(consumers):
        """
        Start all worker processes in parallel across all platforms.

        This method uses a multi-threaded approach to launch all processes
        simultaneously, significantly reducing startup time on all platforms.

        Key optimization: On macOS, using 'fork' method reduces process creation time.
        On Windows, 'spawn' is used but parallel execution still helps.

        Args:
            consumers (list): List of PKMultiProcessorClient instances to start
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # start_time = time.time()
        total_workers = len(consumers)

        # OPTIMIZATION: Pre-configure all workers before starting
        for worker in consumers:
            worker.daemon = True

        # OPTIMIZATION: Use a reasonable number of threads for process startup
        # Too many threads can cause contention, too few wastes time
        if sys.platform.startswith("darwin"):
            max_workers = min(total_workers, 4)  # Cap at 4 threads on Mac
        elif sys.platform.startswith("win"):
            max_workers = min(total_workers, 2)  # Windows needs fewer threads
        else:
            max_workers = min(total_workers, os.cpu_count() or 8)

        OutputControls().printOutput(
            colorText.FAIL
            + f"\n  [+] Using Period:{colorText.END}{colorText.GREEN}{PKScanRunner.configManager.period}{colorText.END}{colorText.FAIL} and Duration:{colorText.END}{colorText.GREEN}{PKScanRunner.configManager.duration}{colorText.END}{colorText.FAIL} with {colorText.GREEN}{total_workers}{colorText.END} consumers and {colorText.GREEN}{max_workers}{colorText.END} workers for scan! You can change this in user config."
            + colorText.END
        )

        # Start all workers in parallel using threads
        # This is safe because Process.start() is non-blocking and returns quickly
        max_workers = max(2, max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all start tasks
            future_to_worker = {executor.submit(worker.start): worker for worker in consumers}

            # Wait for all to complete (they complete quickly since start is non-blocking)
            for future in as_completed(future_to_worker):
                worker = future_to_worker[future]
                try:
                    future.result()  # This will raise any exception that occurred
                except Exception as e:
                    default_logger().debug(f"Error starting worker: {e}", exc_info=True)

        # elapsed = time.time() - start_time
        # OutputControls().printOutput(f"Started all {total_workers} workers in {elapsed:.2f}s")

        # if OutputControls().enableMultipleLineOutput:
        #     OutputControls().moveCursorUpLines(1)

    @staticmethod
    def startWorkersSequential(consumers):
        """
        Legacy sequential worker startup (kept for compatibility).

        This method is slower on all platforms. Use startWorkersParallel instead.

        Args:
            consumers (list): List of PKMultiProcessorClient instances to start
        """
        OutputControls().printOutput(
            colorText.FAIL
            + f"\n  [+] Using Period:{colorText.END}{colorText.GREEN}{PKScanRunner.configManager.period}{colorText.END}{colorText.FAIL} and Duration:{colorText.END}{colorText.GREEN}{PKScanRunner.configManager.duration}{colorText.END}{colorText.FAIL} for scan! You can change this in user config."
            + colorText.END
        )
        start_time = time.time()
        for worker in consumers:
            sys.stdout.write(f"{round(time.time() - start_time)}.")
            worker.daemon = True
            worker.start()
        OutputControls().printOutput(
            f"Started all workers in {round(time.time() - start_time, 4)}s"
        )
        if OutputControls().enableMultipleLineOutput:
            OutputControls().moveCursorUpLines(1)

    @exit_after(
        120
    )  # Should not remain stuck starting the multiprocessing clients beyond this time
    @PKHalo(text="", spinner="dots")
    def startWorkers(consumers):
        """
        Start workers using the parallel method for faster startup.

        This is the main entry point for starting workers. It attempts to use
        parallel startup and falls back to sequential if parallel fails.

        Args:
            consumers (list): List of PKMultiProcessorClient instances to start
        """
        try:
            PKScanRunner.startWorkersParallel(consumers)
        except Exception as e:
            default_logger().debug(
                f"Parallel worker startup failed, falling back to sequential: {e}", exc_info=True
            )
            PKScanRunner.startWorkersSequential(consumers)

    @PKHalo(text="", spinner="dots")
    def terminateAllWorkers(userPassedArgs, consumers, tasks_queue, testing=False):
        """
        Terminate all worker processes and clean up resources.

        Args:
            userPassedArgs: User command line arguments
            consumers (list): List of worker processes to terminate
            tasks_queue (multiprocessing.Queue): Task queue to clear
            testing (bool): Whether in testing mode
        """
        shouldSuppress = (userPassedArgs is None) or (
            userPassedArgs is not None and not userPassedArgs.log
        )
        with SuppressOutput(suppress_stderr=shouldSuppress, suppress_stdout=shouldSuppress):
            # Exit all processes. Without this, it threw error in next screening session
            for worker in consumers:
                try:
                    if testing:  # pragma: no cover
                        if sys.platform.startswith("win"):
                            import signal

                            signal.signal(signal.SIGBREAK, PKScanRunner.shutdown)
                            sleep(1)
                    worker.terminate()
                    default_logger().debug("Worker terminated!")
                except OSError as e:  # pragma: no cover
                    default_logger().debug(e, exc_info=True)
                    continue

            # Flush the queue so depending processes will end
            while True:
                try:
                    _ = tasks_queue.get(False)
                except KeyboardInterrupt:  # pragma: no cover
                    raise KeyboardInterrupt
                except Exception:  # pragma: no cover
                    break
        PKScanRunner.tasks_queue = None
        PKScanRunner.results_queue = None
        PKScanRunner.scr = None
        PKScanRunner.consumers = None

    @staticmethod
    def shutdown(frame, signum):
        """
        Shutdown handler for test coverage.

        Args:
            frame: The current stack frame
            signum: Signal number
        """
        OutputControls().printOutput("Shutting down for test coverage")

    @staticmethod
    def runScan(
        userPassedArgs,
        testing,
        numStocks,
        iterations,
        items,
        numStocksPerIteration,
        tasks_queue,
        results_queue,
        originalNumberOfStocks,
        backtest_df,
        *otherArgs,
        resultsReceivedCb=None,
    ):
        """
        Execute the scan across all stocks using the multiprocessing queues.

        This method manages the distribution of tasks to worker processes and
        collects results as they become available.

        Args:
            userPassedArgs: User command line arguments
            testing (bool): Whether in testing mode
            numStocks (int): Total number of stocks to process
            iterations (int): Number of iterations for queue distribution
            items (list): List of items to process
            numStocksPerIteration (int): Number of stocks per queue iteration
            tasks_queue (multiprocessing.Queue): Task queue
            results_queue (multiprocessing.Queue): Result queue
            originalNumberOfStocks (int): Original number of stocks before splitting
            backtest_df (DataFrame): Backtest results DataFrame
            *otherArgs: Additional arguments for the callback
            resultsReceivedCb (callable): Callback for processing results

        Returns:
            tuple: (backtest_df, lastNonNoneResult)
                   - backtest_df: Updated backtest DataFrame
                   - lastNonNoneResult: The last non-None result received
        """
        queueCounter = 0
        counter = 0
        shouldContinue = True
        lastNonNoneResult = None
        while numStocks:
            if counter == 0 and numStocks > 0:
                if queueCounter < int(iterations):
                    PKScanRunner.populateQueues(
                        items[
                            numStocksPerIteration * queueCounter : numStocksPerIteration
                            * (queueCounter + 1)
                        ],
                        tasks_queue,
                        (queueCounter + 1 == int(iterations))
                        and ((queueCounter + 1) * int(iterations) == originalNumberOfStocks),
                        userPassedArgs,
                    )
                else:
                    PKScanRunner.populateQueues(
                        items[numStocksPerIteration * queueCounter :],
                        tasks_queue,
                        True,
                        userPassedArgs,
                    )
            numStocks -= 1
            result = results_queue.get()
            if result is not None:
                lastNonNoneResult = result

            if resultsReceivedCb is not None:
                shouldContinue, backtest_df = resultsReceivedCb(
                    result, numStocks, backtest_df, *otherArgs
                )
            counter += 1
            # If it's being run under unit testing, let's wrap up if we find at least 1
            # stock or if we've already tried screening through 5% of the list.
            if (not shouldContinue) or (testing and counter >= int(numStocksPerIteration * 0.05)):
                if PKScanRunner.consumers is not None:
                    consumers = PKScanRunner.consumers
                    for worker in consumers:
                        worker.paused = True
                        worker._clear()
                break
            # Add to the queue when we're through 75% of the previously added items already
            if counter >= numStocksPerIteration:  # int(numStocksPerIteration * 0.75):
                queueCounter += 1
                counter = 0

        return backtest_df, lastNonNoneResult
