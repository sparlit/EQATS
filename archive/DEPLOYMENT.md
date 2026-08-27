# 🚀 EQATS v5.0 PRODUCTION DEPLOYMENT GUIDE

## Prerequisites
- **OS**: Linux (Ubuntu 22.04 LTS / Debian 12 recommended) or Windows Server 2022
- **Python**: Version 3.10, 3.11, or 3.12
- **Hardware Minimum**: 4 CPU Cores, 8 GB RAM, NVMe SSD Storage

## Environment Setup

### 1. Repository Installation
```bash
git clone https://github.com/organization/scalper.git /opt/eqats
cd /opt/eqats
```

### 2. Virtual Environment & Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Verification Test Suite Execution
Before deploying to production, run the entire Pytest test suite:
```bash
pytest -v
```
All 64 test cases must pass (100% green).

## Systemd Service Configuration (24x7 Linux VPS)

Create `/etc/systemd/system/eqats.service`:

```ini
[Unit]
Description=EQATS Autonomous Quantum Trading Daemon
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/opt/eqats
ExecStart=/opt/eqats/venv/bin/python main.py --headless
Restart=always
RestartSec=10
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable eqats
sudo systemctl start eqats
sudo systemctl status eqats
```
