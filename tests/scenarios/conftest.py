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


_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Mock mode means no socket leaves this process: not the raw utterance, not anything else (T2).

    The one connect allowed is to a loopback port this process bound itself: asyncio on Windows builds its wake-up
    socketpair that way (bind, listen, connect to the bound port), and TestClient cannot start without it. Ollama on
    localhost:11434 or anything else on the machine is still refused, because this process never bound that port."""
    original_connect, original_bind = socket.socket.connect, socket.socket.bind
    own_loopback_ports: set[int] = set()

    def bind(self, address):
        result = original_bind(self, address)
        name = self.getsockname()
        if isinstance(name, tuple) and name[0] in _LOOPBACK:
            own_loopback_ports.add(name[1])
        return result

    def connect(self, address):
        if isinstance(address, tuple) and address[0] in _LOOPBACK and address[1] in own_loopback_ports:
            return original_connect(self, address)
        raise AssertionError("a scenario test attempted network access; every adapter must be in mock mode")

    monkeypatch.setattr(socket.socket, "bind", bind)
    monkeypatch.setattr(socket.socket, "connect", connect)


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
