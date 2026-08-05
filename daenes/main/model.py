from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address

type IpAddress = IPv4Address | IPv6Address


@dataclass(frozen=True)
class LocalDomain:
    """A container on a network, as docker describes it.

    `names` is every name docker answers for it there, its own and its aliases
    alike, none of them more canonical than the others. `container` is what
    tells two of these asking for one name apart. Whether any of this can be
    served is decided where the zone is built.
    """

    container: str
    names: frozenset[str]
    addresses: tuple[IpAddress, ...]


@dataclass(frozen=True)
class PublishedNetwork:
    """A network asking for a zone, and what is on it right now.

    One with nothing on it still asks for a zone, so that the names that used
    to be there stop resolving.
    """

    name: str
    origin: str
    domains: tuple[LocalDomain, ...]


@dataclass(frozen=True)
class Allowances:
    """The ways of sharing the deployment asked for.

    Both make what a client gets depend on which container or network it
    happened to reach, so daenes refuses them rather than guessing.
    """

    multiple_addresses_per_name: bool = False
    multiple_networks_per_zone: bool = False


@dataclass(frozen=True)
class AddressRecord:
    """A name, and every address it answers with.

    A container's aliases are records of this kind too, rather than something
    pointing at its name: docker's own resolver answers them the same way.
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
