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


import asyncio
import os
import sys

# ------------------------------------------------------------------------------

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.append(root)

import logging
import socket

import ccxt.pro as ccxt
import psutil

KILL_AFTER = 20


async def tcp_kill_after(seconds):
    await asyncio.sleep(seconds)
    logging.debug("tcp_kill")
    current_process = psutil.Process(os.getpid())
    connections = current_process.net_connections(kind="tcp")
    for conn in connections:
        if conn.status == psutil.CONN_ESTABLISHED:
            try:
                # use the connection's real address family instead of forcing AF_INET
                # so that IPv6 (dual-stack) sockets are handled correctly too
                sock = socket.fromfd(conn.fd, conn.family, socket.SOCK_STREAM)
                local_address = conn.laddr.ip
                local_port = conn.laddr.port
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
                logging.info(f"Connection closed: {local_address}:{local_port} -> {conn.raddr.ip}:{conn.raddr.port}")
            except Exception as e:
                logging.exception(f"Error closing connection: {e}")


async def test_abnormal_close():
    print("test_abnormal_close")
    received_network_error = False
    ex = ccxt.binance(
        {
            # 'verbose': True
        }
    )
    ex.set_sandbox_mode(True)
    asyncio.create_task(tcp_kill_after(15))
    start_time = ex.seconds()
    while True:
        if ex.seconds() - start_time > KILL_AFTER:
            break
        try:
            logging.info("calling watch_trades")
            await ex.watch_trades("BTC/USDT:USDT")
            logging.info("watch_trades returned")
        except ccxt.NetworkError as e:
            logging.info(f"received network error: {e}")
            if not received_network_error:
                received_network_error = True
            else:
                break
        except Exception as e:
            logging.info(f"received unexpected exception: {e}")
    assert received_network_error, "Failed to receive network error"
    print("test_abnormal_close between watch calls")
    await ex.watch_trades("BTC/USDT:USDT")
    await tcp_kill_after(1)
    await asyncio.sleep(2)
    await ex.watch_trades("BTC/USDT:USDT")
    await ex.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(test_abnormal_close())
