"""
Root entry point for ELITE QUANTUM AUTONOMOUS TRADING SYSTEM (EQATS).
Provides primary entry point 'python main.py' that delegates directly to src/main.py.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(1, str(ROOT_DIR))

import src.main as src_main

if __name__ == "__main__":
    src_main.run_main()
