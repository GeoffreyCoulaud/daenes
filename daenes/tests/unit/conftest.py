"""Shared fixtures and stand-ins for the daenes unit tests.

The fakes answer the way docker and the file system answer, so that a test
reads like the deployment it stands for. What they answer with comes from
`external_contracts`, whose every key is checked against a real daemon.
"""

from collections.abc import Iterator
from ipaddress import ip_address
from typing import Any

import pytest

from daenes.main.model import IpAddress, LocalDomain, PublishedNetwork, Zone

from ..external_contracts import (
    DNS_NAMES_KEY,
    IPV4_ADDRESS_KEY,
    IPV6_ADDRESS_KEY,
    LABELS_KEY,
    NETWORK_SETTINGS_KEY,
    NETWORKS_KEY,
    NO_ADDRESS,
)

# The zone every test builds against, unless it is about the origin itself.
ORIGIN = "services.internal"
NAMESERVER_ADDRESS = ip_address("10.0.0.53")
TTL = 60


class EndOfTest(Exception):
    """Stands in for an unretryable error, and ends run()'s endless loop."""


class FakeClock:
    """A clock that records what it was asked to wait on, and waits on none."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    def sleep(self, duration: float) -> None:
        self.slept.append(duration)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


class FakeNetworkSource:
    """A deployment the test writes out by hand."""

    def __init__(self, networks: tuple[PublishedNetwork, ...] = ()) -> None:
        self.networks = list(networks)

    def get_published_networks(self) -> list[PublishedNetwork]:
        return list(self.networks)


class FakeZoneStore:
    """Zone files kept in memory, remembering everything written to them."""

    def __init__(self, serials: dict[str, int] | None = None) -> None:
        self.serials = dict(serials or {})
        self.saved: list[Zone] = []

    def get_serial(self, origin: str) -> int | None:
        return self.serials.get(origin)

    def save(self, zone: Zone) -> None:
        self.saved.append(zone)
        self.serials[zone.origin] = zone.serial


def make_domain(
    *names: str,
    addresses: tuple[str, ...] = ("172.20.0.2",),
    container: str | None = None,
) -> LocalDomain:
    """One container on one network, as the docker adapter would report it.

    Two of these are one container unless the test says otherwise.
    """
    known_as = names or ("web",)
    return LocalDomain(
        container=known_as[0] if container is None else container,
        names=frozenset(known_as),
        addresses=tuple(ip_address(address) for address in addresses),
    )


def make_published_network(
    *domains: LocalDomain,
    origin: str = ORIGIN,
    name: str = "compose_services",
) -> PublishedNetwork:
    """One network asking for a zone, and the containers on it."""
    return PublishedNetwork(name=name, origin=origin, domains=domains)


def make_network_settings(
    address: str | None = "172.20.0.2",
    ipv6_address: str | None = None,
    dns_names: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """What docker answers about one container on one network."""
    return {
        IPV4_ADDRESS_KEY: address or NO_ADDRESS,
        IPV6_ADDRESS_KEY: ipv6_address or NO_ADDRESS,
        DNS_NAMES_KEY: list(dns_names) if dns_names is not None else None,
    }


class FakeContainer:
    """A container, seen the way docker's inspect endpoint shows one."""

    def __init__(
        self,
        name: str = "web",
        networks: dict[str, dict[str, Any]] | None = None,
        labels: dict[str, str] | None = None,
        short_id: str = "0123456789ab",
    ) -> None:
        self.name = name
        self.short_id = short_id
        self.labels = labels or {}
        self.attrs = {NETWORK_SETTINGS_KEY: {NETWORKS_KEY: networks or {}}}


class FakeNetwork:
    """A network, whose containers only appear once it has been reloaded."""

    def __init__(
        self,
        name: str = "compose_services",
        labels: dict[str, str] | None = None,
        containers: tuple[FakeContainer, ...] = (),
    ) -> None:
        self.name = name
        self.attrs: dict[str, Any] = {LABELS_KEY: labels}
        self.reloaded = 0
        self._containers = list(containers)

    def reload(self) -> None:
        self.reloaded += 1

    @property
    def containers(self) -> list[FakeContainer]:
        return list(self._containers)


class FakeNetworkCollection:
    def __init__(
        self,
        networks: tuple[FakeNetwork, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self._networks = list(networks)
        self._error = error

    def list(self) -> list[FakeNetwork]:
        if self._error is not None:
            raise self._error
        return list(self._networks)


class FakeDockerClient:
    """A docker daemon that answers whatever the test connected to it."""

    def __init__(
        self,
        networks: tuple[FakeNetwork, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.networks = FakeNetworkCollection(networks, error)


def addresses_of(zone: Zone, name: str) -> tuple[IpAddress, ...] | None:
    """The addresses a zone answers a name with, or None when it does not."""
    for record in zone.addresses:
        if record.name == name:
            return record.addresses
    return None


def names_of(zone: Zone) -> Iterator[str]:
    """Every name a zone answers."""
    return (record.name for record in zone.addresses)
