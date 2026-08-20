# 📖 EAQTS v5.0 OPERATIONAL RUNBOOK

## Daily Operations & Monitoring

### Standard Startup
1. **Interactive Desktop GUI Mode**:
   ```bash
   python main.py
   ```
2. **Headless VPS Daemon Mode**:
   ```bash
   python main.py --headless
   ```

### Pre-Flight Verification Checklist
- Check active database connection: `scalper_brain.db` should be accessible in WAL mode.
- Verify broker terminal status or Universal Broker Gateway credentials in `CFG <GO>` or SQLite `broker_credentials`.
- Confirm spread volatility thresholds in `config.py` (`MAX_SPREAD_PIPS`).

## Incident Management & Emergency Procedures

### Emergency Stop (Kill Switch)
- **GUI**: Click `KILL SWITCH` button on the main toolbar.
- **CLI / Headless**: Send `SIGINT` (Ctrl+C) or execute:
  ```bash
  python main.py --kill
  ```
- **Action Taken**: Cancels all open pending orders, closes active market positions, and halts trading loop execution.

### Database Unlocking / Recovery
In case of ungraceful server termination:
```bash
python -c "import database_infrastructure; database_infrastructure.DatabaseInfrastructure().checkpoint_wal()"
```

### Telemetry & Diagnostics
Check live system diagnostic logs:
```bash
tail -f scalper_state.txt
```
