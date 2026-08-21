# Round 4 — Critic Review

## Scope
Reviewed changes in this commit:
- gui.py: bare except -> except Exception as e + logger.debug
- database.py: 8 silent pass blocks -> loop with debug log + cleaner code
- connector.py: silent pass -> warning log on MT5 login failure
- config.py: silent pass -> debug log on MT5 common path fallback
- .gitignore: expanded to cover build artifacts (nuitka-crash-report.xml, main.build/, main.dist/, *.exe, *.pyd, .venv/, .env)
- Deleted untracked nuitka-crash-report.xml
- docs/INSTITUTIONAL_INTEGRATIONS.md (NEW): catalog of 30 modules
- docs/CIRCUIT_BREAKER.md (NEW): design spec for future implementation
- test_websocket_telemetry.py (NEW): 3 tests for TelemetryStreamServer payload builder

Tests: 67/67 passing (was 64/64), +3 new tests.

## Flaws Identified (3)

### FLAW-001: Loggers declared but never configured
- **Location**: gui.py:16, database.py:9, connector.py:13, config.py:4
- **Issue**: Each module calls `logging.getLogger("name")` but the root logger is never configured anywhere — by default Python emits a `No handlers could be found for logger "X"` warning to stderr when the first record is logged.
- **Risk**: Silent log loss during 24x7 operation; debugging a real incident becomes harder because the warning text gets discarded.
- **Remediation**: Add a one-time `logging.basicConfig(...)` call at the top of `main.py` (the entry point) with `level=logging.INFO` and a stable format. This single-line fix propagates to all child loggers.

### FLAW-002: Telemetry payload has no schema versioning
- **Location**: web_api.py:85-98 TelemetryStreamServer.build_telemetry_payload
- **Issue**: The JSON dict returned has no `schema_version` field. If we add new fields later (e.g., circuit-breaker state from Round 5), existing WS clients won't know to migrate.
- **Risk**: Silent breakage of dashboards after an upgrade.
- **Remediation**: Add `"schema_version": 1` to the payload top level. Bump to 2 when incompatible changes land.

### FLAW-003: test_websocket_telemetry.py imports from sys.path hack
- **Location**: test_websocket_telemetry.py:6-8
- **Issue**: Uses `sys.path.insert(0, ...)` to make `institutional_integrations.web_api` importable. conftest.py likely already does this for the other tests; the hack is redundant and could mask a future test isolation problem.
- **Risk**: Test pollution across modules; CI flakiness when run in unusual working dirs.
- **Remediation**: Remove the `sys.path` block; rely on conftest.py / pytest rootdir for discovery. Verified conftest.py exists in project root.

## Recommendation
APPROVE the PR with the three remediation notes attached as review comments. None of the flaws block the round; they're housekeeping for follow-up rounds.
