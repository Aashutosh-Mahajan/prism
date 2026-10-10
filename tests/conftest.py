from __future__ import annotations

import shutil
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "repos"


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRISM must never touch the network. Any connection attempt fails the test."""

    loopback = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def host_of(address: Any) -> str:
        return str(address[0]) if isinstance(address, tuple) and address else str(address)

    def check(address: Any) -> None:
        # Loopback is local (asyncio's self-pipe on Windows, the viewer's own server).
        if isinstance(address, (str, bytes)):
            return  # a Unix socket path is local IPC, not a network address
        if host_of(address) not in loopback:
            raise NetworkBlocked(f"network access attempted: {address!r}")

    def connect(self: socket.socket, address: Any) -> Any:
        check(address)
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> Any:
        check(address)
        return real_connect_ex(self, address)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        check(address)
        return real_create(address, *args, **kwargs)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        check((host,))
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture(autouse=True)
def _isolated_user_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Keep the per-user consent registry out of the real home directory."""
    home = tmp_path_factory.mktemp("prism-config")
    monkeypatch.setenv("PRISM_CONFIG_HOME", str(home))
    monkeypatch.setenv("PRISM_DAEMON", "0")  # tests that exercise the warm process turn it on
    return home


def copy_fixture(name: str, dest: Path) -> Path:
    target = dest / name
    shutil.copytree(FIXTURES / name, target)
    return target


@pytest.fixture
def tiny_repo(tmp_path: Path) -> Iterator[Path]:
    yield copy_fixture("tiny", tmp_path)


@pytest.fixture
def small_repo(tmp_path: Path) -> Iterator[Path]:
    yield copy_fixture("small", tmp_path)
