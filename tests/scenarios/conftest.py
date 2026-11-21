"""Collection and fixtures for the scenario tests.

`pytest -q tests/` is the documented command and there is no pytest config in the repo, so two things live here:
the scenario files keep the test-matrix names (`T01_standard_run.py`) and are collected by `pytest_collect_file`;
and `backend/` plus the repo root go on sys.path so `app.*` and `integrations.*` import the same way the backend
suite imports them.
"""

from __future__ import annotations

import re
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for entry in (REPO / "backend", REPO):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

SCENARIO_FILE = re.compile(r"^T\d{2}_\w+\.py$")


def pytest_collect_file(file_path: Path, parent):
    """Collect `T<nn>_<slug>.py` next to this file as ordinary test modules. A file named on the command line is
    collected by pytest itself, so it is left alone here or it would run twice."""
    if parent.session.isinitpath(file_path):
        return None
    if file_path.parent == Path(__file__).parent and SCENARIO_FILE.match(file_path.name):
        return pytest.Module.from_parent(parent, path=file_path)
    return None


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Mock mode means no socket leaves this machine: not the raw utterance, not anything else (T2).

    Only a loopback address may connect: asyncio on Windows wires its event loop with an internal socket pair
    (`socket.socketpair` falls back to a 127.0.0.1 connect there), and TestClient cannot start without it. Every other
    address is refused, so a vendor SDK or a cloud model call fails the test instead of leaving the process."""
    real_connect = socket.socket.connect

    def loopback_only(sock, address, *args, **kwargs):
        if isinstance(address, tuple) and address and address[0] in LOOPBACK_HOSTS:
            return real_connect(sock, address, *args, **kwargs)
        raise AssertionError(f"a scenario test attempted network access to {address!r}; every adapter must be in mock mode")

    monkeypatch.setattr(socket.socket, "connect", loopback_only)


@pytest.fixture
def lab_factory(monkeypatch, tmp_path):
    """Build one or more mock-backend labs; every one is closed at teardown."""
    from harness import Lab, make_lab

    made: list[Lab] = []

    def make(**kwargs) -> Lab:
        lab = make_lab(monkeypatch, tmp_path / f"lab{len(made)}", **kwargs)
        made.append(lab)
        return lab

    yield make
    for lab in made:
        lab.close()


@pytest.fixture
def lab(lab_factory):
    """The default lab: fixture clinics and receptionists, Nano and Super stand-ins, clock pinned to the demo week."""
    return lab_factory()
