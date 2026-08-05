"""Shared fixtures and stand-ins for the daenes unit tests.

The fakes answer the way docker and the file system answer, so that a test
reads like the deployment it stands for. What they answer with comes from
`external_contracts`, whose every key is checked against a real daemon.
"""

from collections.abc import Iterator
from ipaddress import ip_address
from threading import Event
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


class FakeChangeNotifier:
    """A deployment whose every answer was decided in advance.

    Answers False once it has run out of them, which is a deployment holding
    still, and raises an answer that is an exception where it stands.
    """

    def __init__(self, changes: tuple[bool | Exception, ...] = ()) -> None:
        self.changes = list(changes)
        self.waited: list[float] = []

    def wait_for_change(self, timeout: float) -> bool:
        self.waited.append(timeout)
        if not self.changes:
            return False
        if isinstance(change := self.changes.pop(0), Exception):
            raise change
        return change


@pytest.fixture
def notifier() -> FakeChangeNotifier:
    return FakeChangeNotifier()


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


# Long enough that a test waiting it out has already failed, short enough that
# the thread which waited it out is gone before the suite is.
QUIET_CEILING = 10


class FakeDockerClient:
    """A docker daemon that answers whatever the test connected to it."""

    def __init__(
        self,
        networks: tuple[FakeNetwork, ...] = (),
        error: Exception | None = None,
        events: tuple[object, ...] = (),
        events_error: Exception | None = None,
    ) -> None:
        self.networks = FakeNetworkCollection(networks, error)
        self.event_filters: list[Any] = []
        self.event_decoding: list[Any] = []
        self._events = events
        self._events_error = events_error

    def events(self, filters: Any = None, decode: Any = None) -> Iterator[object]:
        """The event stream, the way docker-py hands one over.

        An error given as `events_error` is raised by this call, which is a
        daemon that cannot be reached at all; one standing among the events is
        raised where it stands, which is a stream stopping mid-sentence.
        """
        self.event_filters.append(filters)
        self.event_decoding.append(decode)
        if self._events_error is not None:
            raise self._events_error
        return _stream(self._events)


def _stream(events: tuple[object, ...]) -> Iterator[object]:
    """Every event in turn, raising the ones that are exceptions."""
    for event in events:
        if isinstance(event, Exception):
            raise event
        yield event


class FakeQuietDockerClient:
    """A daemon that is up and has nothing to say.

    Its stream stays open and answers nothing, which is what a deployment
    holding still looks like, and the only way to watch a wait run out.
    """

    def __init__(self) -> None:
        self.event_filters: list[Any] = []
        self.event_decoding: list[Any] = []
        self.reading = Event()
        self.done = Event()

    def events(self, filters: Any = None, decode: Any = None) -> Iterator[object]:
        self.event_filters.append(filters)
        self.event_decoding.append(decode)
        return self._quiet()

    def _quiet(self) -> Iterator[object]:
        """Say nothing at all, until the test says the waiting is over."""
        self.reading.set()
        self.done.wait(timeout=QUIET_CEILING)
        yield from ()


@pytest.fixture
def quiet_client() -> Iterator[FakeQuietDockerClient]:
    """A daemon with nothing to say, let go of once the test is over."""
    client = FakeQuietDockerClient()
    yield client
    client.done.set()


def addresses_of(zone: Zone, name: str) -> tuple[IpAddress, ...] | None:
    """The addresses a zone answers a name with, or None when it does not."""
    for record in zone.addresses:
        if record.name == name:
            return record.addresses
    return None


def names_of(zone: Zone) -> Iterator[str]:
    """Every name a zone answers."""
    return (record.name for record in zone.addresses)
