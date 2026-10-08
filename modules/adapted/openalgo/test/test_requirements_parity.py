from __future__ import annotations

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


"""Every runtime library in pyproject.toml is also in the requirements files.

The dev server and Docker install from pyproject.toml, but native Ubuntu
installs (install.sh, install-multi.sh and update.sh) install from
requirements-nginx.txt, and a manual install uses requirements.txt. A library
added to pyproject.toml alone works everywhere except on the servers most
people run. 2.0.2.6 shipped openscript, litellm, agno and ddgs that way:
OpenScript strategies and the agent failed on every updated Ubuntu install,
while the site itself started and looked healthy.
"""


import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT_FILES = ("requirements-nginx.txt", "requirements.txt")


def _key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject() -> dict[str, Requirement]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = (Requirement(spec) for spec in data["project"]["dependencies"])
    return {_key(req.name): req for req in requirements}


def _requirements(filename: str) -> dict[str, Requirement]:
    found = {}
    for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        req = Requirement(line)
        found[_key(req.name)] = req
    return found


@pytest.mark.parametrize("filename", REQUIREMENT_FILES)
def test_every_pyproject_dependency_is_listed(filename):
    listed = _requirements(filename)
    missing = sorted(req.name for key, req in _pyproject().items() if key not in listed)
    assert not missing, (
        f"{filename} does not install {', '.join(missing)}, which pyproject.toml "
        "depends on. Add them with the same version as pyproject.toml."
    )


@pytest.mark.parametrize("filename", REQUIREMENT_FILES)
def test_listed_versions_satisfy_pyproject(filename):
    listed = _requirements(filename)
    wrong = []
    for key, wanted in _pyproject().items():
        have = listed.get(key)
        if have is None:
            continue
        pins = [spec.version for spec in have.specifier if spec.operator == "=="]
        if pins:
            wrong += [
                f"{have.name}=={pin} (pyproject.toml wants {wanted.specifier})"
                for pin in pins
                if not wanted.specifier.contains(pin, prereleases=True)
            ]
        elif have.specifier != wanted.specifier:
            wrong.append(f"{have.name}{have.specifier} (pyproject.toml wants {wanted.specifier})")
    assert not wrong, f"{filename} disagrees with pyproject.toml: {'; '.join(wrong)}"
