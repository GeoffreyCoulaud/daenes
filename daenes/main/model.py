from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address

type IpAddress = IPv4Address | IPv6Address


@dataclass(frozen=True)
class LocalDomain:
    """A container on a network, as docker describes it.

    `container` identifies the container itself, which is the only thing that
    tells one of these apart from another asking for the same name.

    Nothing here is known to be servable yet. Whether these names may be
    written into a zone is decided where the zone is built.
    """

    container: str
    name: str
    addresses: tuple[IpAddress, ...]
    aliases: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PublishedNetwork:
    """A network asking for a zone, and whatever is on it right now.

    A network with nothing on it is not the same as no network at all: the
    first one asks for a zone that answers for nobody, and letting the names
    that used to be on it go on resolving would be worse than saying so.
    """

    origin: str
    domains: tuple[LocalDomain, ...]


@dataclass(frozen=True)
class AddressRecord:
    """A name, and every address it answers with.

    Several addresses on one name is an ordinary answer, not a conflict: the
    client picks. Which of them it can actually reach is not ours to guess.

    A container's aliases are records of this kind too, rather than something
    pointing at its name. Docker's own resolver answers them the same way, and
    a name whose only job is to route does not need a canonical one behind it.
    """

    name: str
    addresses: tuple[IpAddress, ...]


@dataclass(frozen=True)
class Zone:
    """Everything a zone file says, with none of how it is written down."""

    origin: str
    serial: int
    ttl: int
    nameserver: str
    hostmaster: str
    addresses: tuple[AddressRecord, ...]
