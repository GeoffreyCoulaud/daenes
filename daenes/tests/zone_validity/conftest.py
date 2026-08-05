"""Checking what daenes writes with the checker of a real DNS server.

They prove what no test of our own could: that a zone daenes wrote is one BIND
agrees to load. Outside `testpaths`, so `uv run pytest` never needs the binary
they drive; CONTRIBUTING.md says how to install it.
"""

from ipaddress import ip_address
from pathlib import Path

import pytest

from daenes.main.model import Allowances, LocalDomain, PublishedNetwork
from daenes.main.zone_files import FileSystemZoneStore
from daenes.main.zone_synchronizer import ZoneSynchronizer

from ..zone_checker import find_checker
from ..zone_checker import assert_loads as assert_zone_loads
from ..zone_checker import check_zone as check_zone_file

NAMESERVER_ADDRESS = ip_address("10.0.0.53")
ORIGIN = "services.internal"
TTL = 60


class FrozenNetworkSource:
    """A deployment written out by hand, standing in for docker."""

    def __init__(self, networks: tuple[PublishedNetwork, ...]) -> None:
        self._networks = networks

    def get_published_networks(self) -> list[PublishedNetwork]:
        return list(self._networks)


@pytest.fixture(name="checker", scope="session")
def fixture_checker() -> str:
    return find_checker()


def make_domain(
    *names: str,
    addresses: tuple[str, ...] = ("172.20.0.2",),
) -> LocalDomain:
    return LocalDomain(
        container=names[0],
        names=frozenset(names),
        addresses=tuple(ip_address(address) for address in addresses),
    )


def write_zone(
    directory: Path,
    domains: tuple[LocalDomain, ...],
    origin: str = ORIGIN,
    ttl: int = TTL,
    serial: int | None = None,
) -> Path:
    """Write a zone the way a running daenes would, and answer its path."""
    store = FileSystemZoneStore(directory=directory)
    if serial is not None:
        # Start the count wherever the test wants it to end up.
        (directory / f"{origin}.zone").write_text(
            f"@ IN SOA ns admin {serial - 1} 3600 600 604800 600\n",
            encoding="utf-8",
        )
    ZoneSynchronizer(
        source=FrozenNetworkSource(
            (PublishedNetwork(name="compose_services", origin=origin, domains=domains),)
        ),
        store=store,
        nameserver_address=NAMESERVER_ADDRESS,
        ttl=ttl,
        # Everything allowed here, since that is what puts the most into a
        # zone. What a stricter deployment writes is a subset of these records.
        allowances=Allowances(
            multiple_addresses_per_name=True,
            multiple_networks_per_zone=True,
        ),
    ).synchronize()
    return directory / f"{origin}.zone"


def check_zone(checker: str, path: Path, origin: str = ORIGIN) -> tuple[int, str]:
    return check_zone_file(checker, path, origin)


def assert_loads(checker: str, path: Path, origin: str = ORIGIN) -> None:
    assert_zone_loads(checker, path, origin)
