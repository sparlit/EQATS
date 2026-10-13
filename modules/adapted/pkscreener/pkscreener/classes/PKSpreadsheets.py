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
import datetime
import json
import os

import gspread_pandas as gp
from google.oauth2.service_account import Credentials as ServiceAccountCredentials


class PKSpreadsheets:
    def __init__(self, credentialFilePath=None, credentialDictStr=None) -> None:
        self.gClient = None
        self.credentialFilePath = credentialFilePath
        self.credentialDictStr = credentialDictStr
        self.credentials = None
        self.authCredentials = None

    def login(self):
        if self.credentialFilePath is not None:
            with open(self.credentialFilePath) as f:
                self.credentials = json.load(f)
        elif self.credentialDictStr is not None:
            self.credentials = json.loads(self.credentialDictStr)
        else:
            if "GSHEET_SERVICE_ACCOUNT_DEV" in os.environ:
                self.credentials = json.load(os.environ["GSHEET_SERVICE_ACCOUNT_DEV"])
        if self.credentials is None:
            raise ValueError("Credentials cannot be empty!")

        DEFAULT_SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        self.authCredentials = ServiceAccountCredentials.from_service_account_info(
            info=self.credentials,
            scopes=DEFAULT_SCOPES,
        )
        self.gClient = gp.Client(
            creds=self.authCredentials, config=self.credentials, load_dirs=False
        )  # gspread.service_account_from_dict(self.credentials)

    def listFolders(self):
        return self.gClient._get_dirs()

    def getFolder(self, path="/"):
        dirs = self.listFolders()
        # 'id': '0AEHslrN6p5ejUk9PVA'
        # 'name': 'My Drive'
        # 'path': '/'
        folder = None
        if path != "/":
            for dir in dirs:
                if dir["path"] == path:
                    folder = dir
                    break
        else:
            for dir in dirs:
                if dir["path"] == "/":
                    folder = dir
        return folder

    def listWorkbooks(self, path="/", folderId=None):
        if folderId is None:
            folder = self.getFolder(path=path)
            if folder is not None:
                folderId = folder["id"]
        existingWorkbooks = None
        if folderId is not None:
            existingWorkbooks = self.gClient.list_spreadsheet_files_in_folder(folder_id=folderId)
        return existingWorkbooks

    def getWorkbookByName(self, workbookName=None, atPath="/", folderId=None) -> gp.Spread:
        existingWorkbooks = self.listWorkbooks(path=atPath, folderId=folderId)
        workbookOutcome = None
        for workbook in existingWorkbooks:
            if workbook["name"] == workbookName:
                workbookOutcome = self.gClient.open_by_key(workbook["id"])
                break
        return (
            gp.Spread(
                workbookOutcome.id,
                client=self.gClient,
                creds=self.authCredentials,
                config=self.credentials,
            )
            if workbookOutcome is not None
            else None
        )

    def createFolder(self, path="/"):
        if path == "/":
            raise ValueError(
                "Cannot create the root folder! Supply a path value, e.g., /Parent/Child/"
            )
        return self.gClient.create_folder(path=path)

    def createWorkbook(self, workbookName=None, atFolderPath="/"):
        if self.gClient is None:
            raise Exception("You must login first using login() method!")
        if workbookName is None:
            raise ValueError("workbookName cannot be empty!")
        workbookOutcome = None
        # 'id': '0AEHslrN6p5ejUk9PVA'
        # 'name': 'My Drive'
        # 'path': '/'
        folder = self.getFolder(path=atFolderPath)
        if folder is not None:
            folderId = folder["id"]
            workbookOutcome = self.getWorkbookByName(
                workbookName=workbookName, atPath=atFolderPath, folderId=folderId
            )
        else:
            folderInfo = self.createFolder(path=atFolderPath)
            folderId = folderInfo["id"]
        if workbookOutcome is None:
            workbookOutcome = self.gClient.create(title=workbookName, folder_id=folderId)
            # 'id':'18ijLL0uGSYTeRYFb8aQNzJc4m7lCH61T2T8wtpfodSk'
            # 'title':'PKScreener'
            # 'locale':'en_US'
            # 'autoRecalc':'ON_CHANGE'
            # 'timeZone':'Etc/GMT'
            # 'defaultFormat':{'backgroundColor': {'red': 1, 'green': 1, 'blue': 1}, 'padding': {'top': 2, 'right': 3, 'bottom': 2, 'left': 3}, 'verticalAlignment': 'BOTTOM', 'wrapStrategy': 'OVERFLOW_CELL', 'textFormat': {'foregroundColor': {}, 'fontFamily': 'arial,sans,sans-serif', 'fontSize': 10, 'bold': False, 'italic': False, 'strikethrough': False, 'underline': False, 'foregroundColorStyle': {...}}, 'backgroundColorStyle': {'rgbColor': {...}}}
            # 'spreadsheetTheme':{'primaryFontFamily': 'Arial', 'themeColors': [{...}, {...}, {...}, {...}, {...}, {...}, {...}, {...}, {...}]}
            # 'name':'PKScreener'
            # 'createdTime':'2024-03-07T19:40:58.328Z'
            # 'modifiedTime':'2024-03-07T19:40:58.412Z'
            workbookOutcome.share(
                "pkscreener.in@gmail.com", perm_type="user", role="writer", notify=False
            )
            permissions = workbookOutcome.list_permissions()
            for permission in permissions:
                if (
                    permission["emailAddress"] == "pkscreener.in@gmail.com"
                    and permission["role"] == "writer"
                ):
                    workbookOutcome.transfer_ownership(permission_id=permission["id"])
                    break
        return (
            gp.Spread(
                workbookOutcome.id,
                client=self.gClient,
                creds=self.authCredentials,
                config=self.credentials,
            )
            if workbookOutcome is not None
            else None
        )

    def addWorksheet(self, worksheetName=None, workbook: gp.Spread = None):
        assert workbook is not None
        assert worksheetName is not None
        workbook.open_sheet(sheet=worksheetName, create=True)
        return workbook.sheet if workbook.sheet.title == worksheetName else None

    def findSheet(self, worksheetName=None, workbook: gp.Spread = None):
        return workbook.find_sheet(sheet=worksheetName)

    def df_to_sheet(
        self, df=None, sheetName=None, folderName="PKScreener", workbookName="PKScreener"
    ):
        self.login()
        valueAddColumns = ["EntryDate", "EntryTime", "ScanLabel"]
        today = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
        date = today.date().strftime("%Y-%m-%d")
        time = today.strftime("%H:%M:%S")
        for col in valueAddColumns:
            if col not in df.columns:
                df[col] = (
                    date
                    if col == valueAddColumns[0]
                    else (time if col == valueAddColumns[1] else sheetName)
                )
        workbook = self.getWorkbookByName(workbookName=workbookName, atPath=folderName)
        sheet = self.addWorksheet(worksheetName=sheetName, workbook=workbook)
        currentMaxRow = sheet.row_count
        currentMaxCol = sheet.col_count
        currentMaxRow = currentMaxRow + 1 if currentMaxRow > 1 else currentMaxRow
        sheet.resize(len(df) + currentMaxRow, max(len(df.columns), currentMaxCol))
        workbook.df_to_sheet(
            df=df, start=(currentMaxRow, 1), freeze_headers=False, freeze_index=True, sheet=sheet
        )
        sheet.freeze(rows=1, cols=1)
