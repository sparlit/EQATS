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


#!/usr/bin/env python

# Python HTTPServer server for response code testing (localhost:8080 by default)

try:
    # Python 3
    import sys
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    from http.server import test as test_orig

    def test(*args):
        test_orig(*args, port=int(sys.argv[1]) if len(sys.argv) > 1 else 8080)

except ImportError:  # Python 2
    from BaseHTTPServer import HTTPServer, test
    from SimpleHTTPServer import SimpleHTTPRequestHandler


class TestRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # self.send_error(100, 'Continue')
        # self.send_error(101, 'Switching Protocols')
        # self.send_error(200, 'OK')
        # self.send_error(201, 'Created')
        # self.send_error(202, 'Accepted')
        # self.send_error(203, 'Non-Authoritative Information')
        # self.send_error(204, 'No Content')
        # self.send_error(205, 'Reset Content')
        # self.send_error(206, 'Partial Content')
        # self.send_error(300, 'Multiple Choices')
        # self.send_error(301, 'Moved Permanently')
        # self.send_error(302, 'Found')
        # self.send_error(303, 'See Other')
        # self.send_error(304, 'Not Modified')
        # self.send_error(305, 'Use Proxy')
        # self.send_error(307, 'Temporary Redirect')
        # self.send_error(400, 'Bad Request')
        # self.send_error(401, 'Unauthorized')
        # self.send_error(402, 'Payment Required')
        # self.send_error(403, 'Forbidden')
        self.send_error(404, "Not Found")
        # self.send_error(405, 'Method Not Allowed')
        # self.send_error(406, 'Not Acceptable')
        # self.send_error(407, 'Proxy Authentication Required')
        # self.send_error(408, 'Request Timeout')
        # self.send_error(409, 'Conflict')
        # self.send_error(410, 'Gone')
        # self.send_error(411, 'Length Required')
        # self.send_error(412, 'Precondition Failed')
        # self.send_error(413, 'Request Entity Too Large')
        # self.send_error(414, 'Request-URI Too Long')
        # self.send_error(415, 'Unsupported Media Type')
        # self.send_error(416, 'Requested Range Not Satisfiable')
        # self.send_error(417, 'Expectation Failed')
        # self.send_error(500, 'Internal Server Error')
        # self.send_error(501, 'Not Implemented')
        # self.send_error(502, 'Bad Gateway')
        # self.send_error(503, 'Service Unavailable')
        # self.send_error(504, 'Gateway Timeout')
        # self.send_error(505, 'HTTP Version Not Supported')


if __name__ == "__main__":
    test(TestRequestHandler, HTTPServer)
