from typing import Any
import os
import sys

tests_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(tests_dir, ".."))
src_dir = os.path.join(repo_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import config

worker_id = os.environ.get('PYTEST_XDIST_WORKER')
if worker_id:
    config.DB_PATH = f'scalper_{worker_id}.db'
