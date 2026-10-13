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


import sys

import numpy as np
from numba import boolean, float64, int64
from numba.experimental import jitclass

UNCHANGED = 0
CHANGED = 1
INSERTED = 2
IN_THE_BOOK_DELETION = 0
OUT_OF_BOOK_DELETION_BELOW = 1
OUT_OF_BOOK_DELETION_ABOVE = 2


@jitclass
class DiffOrderBookSnapshot:
    num_levels: int64
    curr_bids: float64[:, :]
    curr_asks: float64[:, :]
    prev_bids: float64[:, :]
    prev_asks: float64[:, :]
    bid_delete_lvs: float64[:, :]
    ask_delete_lvs: float64[:, :]
    curr_bid_lv: int64
    curr_ask_lv: int64
    prev_bid_lv: int64
    prev_ask_lv: int64
    init: boolean
    tick_size: float64
    lot_size: float64

    def __init__(self, levels: int, tick_size: float, lot_size: float) -> None:
        self.num_levels = levels
        # [num_levels, {price, qty, is_updated}]
        self.curr_bids = np.zeros((levels, 3), float64)
        self.curr_asks = np.zeros((levels, 3), float64)
        self.prev_bids = np.zeros((levels, 3), float64)
        self.prev_asks = np.zeros((levels, 3), float64)
        # [num_levels, {price, delete_type}]
        self.bid_delete_lvs = np.zeros((levels, 2), float64)
        self.ask_delete_lvs = np.zeros((levels, 2), float64)
        self.curr_bid_lv = 0
        self.curr_ask_lv = 0
        self.prev_bid_lv = 0
        self.prev_ask_lv = 0
        self.init = True
        self.tick_size = tick_size
        self.lot_size = lot_size

    def snapshot(
        self, bid_px: np.ndarray, bid_qty: np.ndarray, ask_px: np.ndarray, ask_qty: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if len(bid_px) != len(bid_qty) or len(ask_px) != len(ask_qty):
            raise ValueError

        self.curr_bid_lv, self.prev_bid_lv = 0, self.curr_bid_lv
        self.curr_ask_lv, self.prev_ask_lv = 0, self.curr_ask_lv
        # Swaps the snapshots.
        self.curr_bids, self.prev_bids = self.prev_bids, self.curr_bids
        self.curr_asks, self.prev_asks = self.prev_asks, self.curr_asks

        self.curr_bid_lv = 0
        for i in range(len(bid_px)):
            self.curr_bids[self.curr_bid_lv, 0] = bid_px[i]
            self.curr_bids[self.curr_bid_lv, 1] = bid_qty[i]
            self.curr_bids[self.curr_bid_lv, 2] = CHANGED
            self.curr_bid_lv += 1

        self.curr_ask_lv = 0
        for i in range(len(ask_px)):
            self.curr_asks[self.curr_ask_lv, 0] = ask_px[i]
            self.curr_asks[self.curr_ask_lv, 1] = ask_qty[i]
            self.curr_asks[self.curr_ask_lv, 2] = CHANGED
            self.curr_ask_lv += 1

        if self.init:
            self.init = False
            return (
                self.curr_bids,
                self.curr_asks,
                self.bid_delete_lvs[:0],
                self.ask_delete_lvs[:0],
            )

        # Processes the bid snapshot
        curr_high_px_tick = 0
        curr_low_px_tick = sys.maxsize
        for curr_lv in range(self.curr_bid_lv):
            curr_px_tick = np.round(self.curr_bids[curr_lv, 0] / self.tick_size)
            if curr_px_tick < curr_low_px_tick:
                curr_low_px_tick = curr_px_tick
            if curr_px_tick > curr_high_px_tick:
                curr_high_px_tick = curr_px_tick

        # Checks which levels are deleted.
        bids_delete_lv = 0
        for prev_lv in range(self.prev_bid_lv):
            prev_px_tick = np.round(self.prev_bids[prev_lv, 0] / self.tick_size)
            if prev_px_tick < curr_low_px_tick:
                self.bid_delete_lvs[bids_delete_lv, 0] = prev_px_tick * self.tick_size
                self.bid_delete_lvs[bids_delete_lv, 1] = OUT_OF_BOOK_DELETION_BELOW
                bids_delete_lv += 1
            elif prev_px_tick > curr_high_px_tick:
                self.bid_delete_lvs[bids_delete_lv, 0] = prev_px_tick * self.tick_size
                self.bid_delete_lvs[bids_delete_lv, 1] = OUT_OF_BOOK_DELETION_ABOVE
                bids_delete_lv += 1
            else:
                exist = False
                for curr_lv in range(self.curr_bid_lv):
                    curr_px_tick = np.round(self.curr_bids[curr_lv, 0] / self.tick_size)
                    if prev_px_tick == curr_px_tick:
                        exist = True
                        break
                if not exist:
                    self.bid_delete_lvs[bids_delete_lv, 0] = prev_px_tick * self.tick_size
                    self.bid_delete_lvs[bids_delete_lv, 1] = IN_THE_BOOK_DELETION
                    bids_delete_lv += 1

        # Sets the update flag.
        for curr_lv in range(self.curr_bid_lv):
            curr_px_tick = np.round(self.curr_bids[curr_lv, 0] / self.tick_size)
            exist = False
            for prev_lv in range(self.prev_bid_lv):
                prev_px_tick = np.round(self.prev_bids[prev_lv, 0] / self.tick_size)
                if prev_px_tick == curr_px_tick:
                    exist = True
                    if np.round(self.curr_bids[curr_lv, 1] / self.lot_size) == np.round(
                        self.prev_bids[prev_lv, 1] / self.lot_size
                    ):
                        self.curr_bids[curr_lv, 2] = UNCHANGED
                    break
            if not exist:
                self.curr_bids[curr_lv, 2] = INSERTED

        # Processes the ask snapshot
        curr_high_px_tick = 0
        curr_low_px_tick = sys.maxsize
        for curr_lv in range(self.curr_ask_lv):
            curr_px_tick = np.round(self.curr_asks[curr_lv, 0] / self.tick_size)
            if curr_px_tick < curr_low_px_tick:
                curr_low_px_tick = curr_px_tick
            if curr_px_tick > curr_high_px_tick:
                curr_high_px_tick = curr_px_tick

        # Checks which levels are deleted.
        asks_delete_lv = 0
        for prev_lv in range(self.prev_ask_lv):
            prev_px_tick = np.round(self.prev_asks[prev_lv, 0] / self.tick_size)
            if prev_px_tick < curr_low_px_tick:
                self.ask_delete_lvs[asks_delete_lv, 0] = prev_px_tick * self.tick_size
                self.ask_delete_lvs[asks_delete_lv, 1] = OUT_OF_BOOK_DELETION_BELOW
                asks_delete_lv += 1
            elif prev_px_tick > curr_high_px_tick:
                self.ask_delete_lvs[asks_delete_lv, 0] = prev_px_tick * self.tick_size
                self.ask_delete_lvs[asks_delete_lv, 1] = OUT_OF_BOOK_DELETION_ABOVE
                asks_delete_lv += 1
            else:
                exist = False
                for curr_lv in range(self.curr_ask_lv):
                    curr_px_tick = np.round(self.curr_asks[curr_lv, 0] / self.tick_size)
                    if prev_px_tick == curr_px_tick:
                        exist = True
                        break
                if not exist:
                    self.ask_delete_lvs[asks_delete_lv, 0] = prev_px_tick * self.tick_size
                    self.ask_delete_lvs[asks_delete_lv, 1] = IN_THE_BOOK_DELETION
                    asks_delete_lv += 1

        # Sets the update flag.
        for curr_lv in range(self.curr_ask_lv):
            curr_px_tick = np.round(self.curr_asks[curr_lv, 0] / self.tick_size)
            exist = False
            for prev_lv in range(self.prev_ask_lv):
                prev_px_tick = np.round(self.prev_asks[prev_lv, 0] / self.tick_size)
                if prev_px_tick == curr_px_tick:
                    exist = True
                    if np.round(self.curr_asks[curr_lv, 1] / self.lot_size) == np.round(
                        self.prev_asks[prev_lv, 1] / self.lot_size
                    ):
                        self.curr_asks[curr_lv, 2] = UNCHANGED
                    break
            if not exist:
                self.curr_asks[curr_lv, 2] = INSERTED

        return (
            self.curr_bids,
            self.curr_asks,
            self.bid_delete_lvs[:bids_delete_lv, :],
            self.ask_delete_lvs[:asks_delete_lv, :],
        )
