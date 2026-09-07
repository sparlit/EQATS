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
python client for tectonic server
"""

import asyncio
import json
import socket
import struct
import sys
import time
from io import StringIO

import ffi
import numpy as np
import pandas as pd


class TectonicDB:
    """
    Example Usage:
        from tectonic import TectonicDB
        import json
        import asyncio

        async def subscribe(name):
            db = TectonicDB()
            print(await db.subscribe(name))
            while 1:
                _, item = await db.poll()
                if item == b"NONE":
                    await asyncio.sleep(0.01)
                else:
                    yield json.loads(item)

        class TickBatcher(object):
            def __init__(self, db_name):
                self.one_batch = []
                self.db_name = db_name

            async def batch(self):
                generator = subscribe(self.db_name)
                async for item in generator:
                    self.one_batch.append(item)

            async def timer(self):
                while 1:
                    await asyncio.sleep(5)
                    print(len(self.one_batch))


        if __name__ == '__main__':
            loop = asyncio.get_event_loop()
            proc = TickBatcher("bnc_xrp_btc")
            loop.create_task(proc.batch())
            loop.create_task(proc.timer())
            loop.run_forever()
            loop.close()
    """

    def __init__(self, host="localhost", port=9001):
        self.subscribed = False
        self.host = host
        self.port = port

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_address = (host, port)
        self.sock.connect(server_address)

    async def cmd(self, cmd):
        loop = asyncio.get_event_loop()
        if type(cmd) != str:
            message = (cmd.decode() + "\n").encode()
        else:
            message = (cmd + "\n").encode()
        loop.sock_sendall(self.sock, message)

        if "GET" in cmd and "JSON" not in cmd and "CSV" not in cmd:
            return await self._recv_dtf()
        return await self._recv_text()

    async def _recv_dtf(self):
        success, data = await self._recv_text()
        ups = ffi.parse_stream(data)
        return success, ups

    async def _recv_text(self):
        loop = asyncio.get_event_loop()
        header = await loop.sock_recv(self.sock, 9)
        current_len = len(header)
        while current_len < 9:
            header += await loop.sock_recv(self.sock, 9 - current_len)
            current_len = len(header)

        success, bytes_to_read = struct.unpack(">?Q", header)
        if bytes_to_read == 0:
            return success, ""

        body = await loop.sock_recv(self.sock, 1)
        body_len = len(body)
        while body_len < bytes_to_read:
            len_to_read = bytes_to_read - body_len
            len_to_read = min(len_to_read, 32)
            body += await loop.sock_recv(self.sock, len_to_read)
            body_len = len(body)
        return success, body

    def destroy(self):
        self.sock.close()

    async def info(self):
        return await self.cmd("INFO")

    async def countall(self):
        return await self.cmd("COUNT ALL")

    async def countall_in_mem(self):
        return await self.cmd("COUNT ALL IN MEM")

    async def ping(self):
        return await self.cmd("PING")

    async def help(self):
        return await self.cmd("HELP")

    async def insert(self, ts, seq, is_trade, is_bid, price, size, dbname):
        return await self.cmd(
            "INSERT {}, {}, {} ,{}, {}, {}; INTO {}".format(
                ts,
                seq,
                "t" if is_trade else "f",
                "t" if is_bid else "f",
                price,
                size,
                dbname,
            ),
        )

    async def add(self, ts, seq, is_trade, is_bid, price, size):
        return await self.cmd(
            "ADD {}, {}, {} ,{}, {}, {};".format(
                ts,
                seq,
                "t" if is_trade else "f",
                "t" if is_bid else "f",
                price,
                size,
            ),
        )

    async def getall(self):
        success, ret = await self.cmd("GET ALL")
        return success, list(map(lambda x: x.to_dict(), ret))

    async def get(self, n):
        success, ret = await self.cmd(f"GET {n}")
        if success:
            return success, list(map(lambda x: x.to_dict(), ret))
        return False, None

    async def clear(self):
        return await self.cmd("CLEAR")

    async def clearall(self):
        return await self.cmd("CLEAR ALL")

    async def flush(self):
        return await self.cmd("FLUSH")

    async def flushall(self):
        return await self.cmd("FLUSH ALL")

    async def create(self, dbname):
        return await self.cmd(f"CREATE {dbname}")

    async def use(self, dbname):
        return await self.cmd(f"USE {dbname}")

    async def unsubscribe(self):
        await self.cmd("UNSUBSCRIBE")
        self.subscribed = False

    async def subscribe(self, dbname):
        res = await self.cmd(f"SUBSCRIBE {dbname}")
        if res[0]:
            self.subscribed = True
        return res

    async def poll(self):
        return await self.cmd("")

    async def range(self, dbname, start, finish):
        self.use(dbname)
        data = await self.cmd(f"GET ALL FROM {start} TO {finish} AS CSV".encode())
        data = data[1]
        return data
