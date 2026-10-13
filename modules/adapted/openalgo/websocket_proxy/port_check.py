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


import socket
import time

from utils.logging import get_logger

logger = get_logger("websocket_proxy")


def is_port_in_use(host, port, wait_time=0, log=True):
    """
    Check if a port is already in use on a specific host

    Args:
        host (str): Hostname to check
        port (int): Port number to check
        wait_time (float): Time to wait for port to be released (for cleanup scenarios)
        log (bool): Log when the port is busy. The proxy supervisor polls
            quietly while it waits for a dying child to release its ports.

    Returns:
        bool: True if the port is in use, False otherwise
    """
    # If wait_time is specified, check multiple times
    if wait_time > 0:
        attempts = int(wait_time * 10)  # Check every 0.1 seconds
        for attempt in range(attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((host, port))
                    # Port is not in use
                    return False
                except OSError:
                    if attempt == attempts - 1:  # Last attempt
                        if log:
                            logger.info(
                                f"Port {port} is still in use on {host} after {wait_time}s wait"
                            )
                        return True
                    time.sleep(0.1)  # Wait 0.1 second before next attempt
    else:
        # Single check
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                # Port is not in use
                return False
            except OSError:
                # Port is in use
                if log:
                    logger.info(f"Port {port} is already in use on {host}")
                return True


def find_available_port(start_port=8899, max_attempts=10):
    """
    Find an available port starting from the given port

    Args:
        start_port (int): Port to start searching from
        max_attempts (int): Maximum number of ports to try

    Returns:
        int: Available port number, or None if no port is available
    """
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use("127.0.0.1", port):
            return port

    logger.error(
        f"Could not find an available port after {max_attempts} attempts starting from {start_port}"
    )
    return None
