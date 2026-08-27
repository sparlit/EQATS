import os
import sys

import config

# Ensure the repository root directory is in sys.path
repo_root = os.path.dirname(os.path.abspath(__file__))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Set worker-isolated database path for pytest xdist parallel test workers
worker_id = os.environ.get("PYTEST_XDIST_WORKER")
if worker_id:
    config.DB_PATH = f"scalper_{worker_id}.db"
