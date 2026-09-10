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
import time

import csvtodb as db


class posGain:
    def analyzeScript(self, script, df, args):
        self.sl = int(args[0])
        self.ll = int(args[1])
        ret = ""
        tail = df.tail(self.ll)
        if len(tail.index) == self.ll:
            incrSL = (tail["Close"][-1] - tail["Close"][-self.sl]) / tail["Close"][-self.sl]
            incrLL = (tail["Close"][-1] - tail["Close"][-self.ll]) / tail["Close"][-self.ll]
            posRet = (script, str("%.2f" % (incrSL * 100)), str("%.2f" % (incrLL * 100)))
            ret = ("", posRet)[incrSL > 0]
        return ret

    def report(self, rep):
        report = sorted(rep, reverse=True, key=lambda x: x[1])
        slHeader = str(self.sl) + "_DAY_MOVE"
        llHeader = str(self.ll) + "_DAY_MOVE"
        F = open("posGain" + time.strftime("%Y%m%d-%H%M%S") + ".csv", "w")
        F.write("%20s,%12s,%12s" % ("SYMBOL", slHeader, llHeader))
        F.write("\n".join(("%20s,%12s,%12s" % (x[0], x[1], x[2])) for x in report))
        F.close()


def report(c, args):
    com = c()
    rep = []
    s = db.getLastDayScripts()
    if s != -1:
        sc = [str(r[0]) for r in s]
        for scr in sc:
            df = db.obtainQuotes(scr)
            r = com.analyzeScript(scr, df, args)
            if r:
                rep.append(r)
        com.report(rep)


def _printUsage():
    pass


def main(args):
    commands = {
        "posGain": posGain,
    }
    if args:
        c = args[0]
        c = c[1:]
        try:
            f = commands[c]
        except KeyError:
            msg = "Unsupported function"
            raise ValueError(msg)
        report(f, args[1:])
    else:
        _printUsage()


if __name__ == "__main__":
    main(sys.argv[1:])
