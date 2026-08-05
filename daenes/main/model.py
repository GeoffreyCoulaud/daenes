from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address

type IpAddress = IPv4Address | IPv6Address


@dataclass(frozen=True)
class LocalDomain:
    """A container on a network, as docker describes it.

    Nothing here is known to be servable yet. Whether these names may be
    written into a zone is decided where the zone is built.
    """

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
    """

    name: str
    addresses: tuple[IpAddress, ...]


@dataclass(frozen=True)
class AliasRecord:
    """A name that answers by pointing at another name in the same zone."""

    name: str
    target: str


@dataclass(frozen=True)
class Zone:
    """Everything a zone file says, with none of how it is written down."""

    origin: str
    serial: int
    ttl: int
    nameserver: str
    hostmaster: str
    addresses: tuple[AddressRecord, ...]
    aliases: tuple[AliasRecord, ...]
