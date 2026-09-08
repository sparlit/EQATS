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


#!/usr/bin/env python3
"""Single script to run the Indian Stock Tracker web app on http://localhost:8080.

Usage:
    python run.py

This script:
1. Initializes the SQLite database if needed
2. Kills any process using port 8080 (if it's a conflicting application)
3. Launches the Flask web UI (dashboard, stocks browser, price explorer, suggestions)
4. Opens http://localhost:8080 in your browser
"""

import os
import platform
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def init_database():
    """Initialize the SQLite database by running models.init_db()."""
    print("Initializing database...")
    try:
        from models import init_db

        init_db(db_version="2.0")
        print("Database initialized successfully.")
        return True
    except Exception as e:
        print(f"Warning: Database initialization had an issue: {e}")
        # This might happen if tables already exist, which is fine
        return True


def init_mutual_funds_database():
    """Initialize the mutual funds database."""
    print("Initializing mutual funds database...")
    try:
        from flask_app import init_mutual_funds_db

        init_mutual_funds_db()
        print("Mutual funds database initialized successfully.")
    except Exception as e:
        print(f"Warning: Mutual funds database initialization: {e}")


def kill_process_on_port(port):
    """Kill any process currently listening on the specified port."""
    print(f"Checking if port {port} is in use...")

    # Check if port is in use
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(("127.0.0.1", port))
    sock.close()

    if result != 0:
        # Port is not in use, nothing to kill
        print(f"Port {port} is not in use.")
        return True

    print(f"Port {port} is in use. Attempting to kill the process...")

    try:
        system = platform.system()

        if system == "Darwin":  # macOS
            # Use lsof to find the process
            result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
            pids = result.stdout.strip().split("\n")
            pids = [pid for pid in pids if pid]

            if pids:
                for pid in pids:
                    print(f"Killing process PID {pid} on port {port}...")
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                print(f"Successfully killed processes on port {port}.")
                return True
            print(f"No process found using lsof on port {port}.")
            return False
        if system == "Linux":
            # Use lsof or fuser
            result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
            pids = result.stdout.strip().split("\n")
            pids = [pid for pid in pids if pid]

            if pids:
                for pid in pids:
                    print(f"Killing process PID {pid} on port {port}...")
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                print(f"Successfully killed processes on port {port}.")
                return True
            # Try fuser as fallback
            result = subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Successfully killed process on port {port} using fuser.")
                return True
            print(f"Could not kill process on port {port}.")
            return False
        if system == "Windows":
            # Use netstat and taskkill
            result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
            for line in result.stdout.split("\n"):
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = parts[-1] if len(parts) > 1 else None
                    if pid:
                        print(f"Killing process PID {pid} on port {port}...")
                        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            print(f"Attempted to kill processes on port {port}.")
            return True
        print(f"Unsupported operating system: {system}.")
        return False
    except Exception as e:
        print(f"Error trying to kill process on port {port}: {e}")
        return False


def launch_flask_app():
    """Launch the Flask web application on port 8080."""
    print("Starting Flask web application...")
    print("Opening browser at http://localhost:8080")
    print("Press Ctrl+C to stop the server\n")

    # Open browser after a short delay to let the server start
    def open_browser():
        time.sleep(1)
        webbrowser.open("http://localhost:8080")

    import threading

    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    # Run the Flask app
    # use_reloader=False prevents Werkzeug from spawning a child process
    # which avoids port conflicts and process-killing issues
    from flask_app import app

    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=8080)


def main():
    """Main entry point for the run.py script."""
    print("=" * 60)
    print("Indian Stock Tracker - Web UI Launcher")
    print("=" * 60)
    print()

    # Initialize databases
    init_database()
    init_mutual_funds_database()

    # Kill any process on port 8080 before starting
    print()
    kill_process_on_port(8080)

    # Wait briefly to ensure the port is fully released
    print("Waiting briefly for port to become free...")
    time.sleep(0.5)

    print()
    print("=" * 60)
    print("Starting web server...")
    print("Access the app at: http://localhost:8080")
    print("=" * 60)
    print()

    launch_flask_app()


if __name__ == "__main__":
    main()
