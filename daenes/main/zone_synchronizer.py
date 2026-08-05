import logging
from collections import Counter
from collections.abc import Iterator

from .dns_names import MAX_NAME_LENGTH, is_valid_name, normalize
from .model import AddressRecord, Allowances, IpAddress, LocalDomain, Zone
from .ports import NetworkSource, ZoneStore

# The zone's own nameserver and hostmaster, relative to its origin. A container
# is refused the nameserver's name: that record is the zone's own plumbing, the
# one its NS record points at, and not something docker is authoritative about.
NAMESERVER_NAME = "ns"
HOSTMASTER_NAME = "admin"

# A serial is unsigned 32 bit arithmetic, and wraps around (RFC 1982).
SERIAL_MODULO = 2**32
FIRST_SERIAL = 1


class ZoneSynchronizer:
    """Turns what the deployment says into the zones a DNS server serves.

    Knows nothing of docker or of files: it reads networks through one port and
    writes zones through another.
    """

    def __init__(
        self,
        source: NetworkSource,
        store: ZoneStore,
        nameserver_address: IpAddress,
        ttl: int,
        allowances: Allowances,
    ) -> None:
        self._source = source
        self._store = store
        self._nameserver_address = nameserver_address
        self._ttl = ttl
        self._allowances = allowances
        # The last zone written for each origin, so an unchanged zone is left
        # alone rather than rewritten with a new serial, which every secondary
        # server would take for news. Only records can change while the process
        # lives, since the rest of a zone comes from the configuration.
        self._written: dict[str, Zone] = {}

    def synchronize(self) -> None:
        """Bring every zone the deployment describes up to date."""
        domains_by_origin = self._group_by_origin()
        # In a settled order, so that two runs over one deployment write and
        # log the same way.
        for origin in sorted(domains_by_origin):
            self._synchronize_zone(origin, domains_by_origin[origin])

    def _group_by_origin(self) -> dict[str, list[LocalDomain]]:
        """Gather the containers by the zone they belong to.

        Two docker networks naming one origin land in one zone, which the
        deployment has to have asked for.
        """
        domains: dict[str, list[LocalDomain]] = {}
        networks: dict[str, list[str]] = {}
        for network in self._source.get_published_networks():
            origin = normalize(network.origin)
            domains.setdefault(origin, []).extend(network.domains)
            networks.setdefault(origin, []).append(network.name)
        return {
            origin: found
            for origin, found in domains.items()
            if self._is_servable_origin(origin, networks[origin])
        }

    def _is_servable_origin(self, origin: str, networks: list[str]) -> bool:
        """Whether a zone may be built on this origin, saying why when not."""
        if not is_valid_name(origin):
            logging.error(
                "Ignoring the network asking for %r: "
                "a domain is made of labels of letters, digits and hyphens",
                origin,
            )
            return False
        if "." not in origin:
            logging.error(
                "Ignoring the network asking for %r: "
                "a domain needs more than one label, did you mean %s.internal?",
                origin,
                origin,
            )
            return False
        if len(networks) > 1 and not self._allowances.multiple_networks_per_zone:
            logging.warning(
                "Ignoring the zone %r entirely: %d networks ask for it (%s), and "
                "a container on one of them would answer for names nothing on "
                "the others can reach. Set ALLOW_MULTIPLE_NETWORKS_PER_ZONE to "
                "true to merge them",
                origin,
                len(networks),
                ", ".join(sorted(networks)),
            )
            return False
        return True

    def _synchronize_zone(self, origin: str, domains: list[LocalDomain]) -> None:
        addresses = self._build_records(origin, domains)
        written = self._written.get(origin)
        if written is not None and written.addresses == addresses:
            logging.debug("Zone %s did not change, leaving it alone", origin)
            return
        zone = Zone(
            origin=origin,
            serial=self._get_next_serial(origin),
            ttl=self._ttl,
            nameserver=NAMESERVER_NAME,
            hostmaster=HOSTMASTER_NAME,
            addresses=addresses,
        )
        self._store.save(zone)
        self._written[origin] = zone
        logging.info("Wrote zone %s with serial %d", origin, zone.serial)

    def _get_next_serial(self, origin: str) -> int:
        """The serial to write, one past whatever the stored zone claims.

        Read back from the store rather than remembered, so a restart carries
        on from where the previous run left off instead of sending every
        secondary server back in time.
        """
        previous = self._store.get_serial(origin)
        if previous is None:
            return FIRST_SERIAL
        return (previous + 1) % SERIAL_MODULO

    def _build_records(
        self,
        origin: str,
        domains: list[LocalDomain],
    ) -> tuple[AddressRecord, ...]:
        """Turn the containers of one zone into the records it answers with."""
        addresses: dict[str, set[IpAddress]] = {
            NAMESERVER_NAME: {self._nameserver_address}
        }
        # Which containers ended up answering on each name, to say so when one
        # is dropped over them. The nameserver is nobody's container.
        containers: dict[str, set[str]] = {}
        for domain in sorted(domains, key=lambda domain: domain.name):
            for name in self._get_names(origin, domain):
                addresses.setdefault(name, set()).update(domain.addresses)
                containers.setdefault(name, set()).add(domain.container)
        if not self._allowances.multiple_addresses_per_name:
            _drop_shared_names(addresses, containers)
        return tuple(
            AddressRecord(
                name=name,
                addresses=tuple(sorted(found, key=_address_sort_key)),
            )
            for name, found in sorted(addresses.items())
        )

    def _get_names(self, origin: str, domain: LocalDomain) -> Iterator[str]:
        """Every name one container answers to, its own and its aliases.

        Docker's own resolver makes no difference between the two, and neither
        does this: an alias is a name answering with the same addresses. Each
        of them stands on its own, so a container whose name cannot be served
        is still reached through the aliases that can.
        """
        for label in [domain.name, *sorted(domain.aliases)]:
            name = self._make_name(origin, label)
            if name is not None:
                yield name

    @staticmethod
    def _make_name(origin: str, label: str) -> str | None:
        """The name to write for a container, or None to leave it out."""
        name = normalize(label)
        if not is_valid_name(name):
            logging.warning(
                "Ignoring the name %r of zone %s: it is not a valid domain name, "
                "give that container a domain of its own instead",
                label,
                origin,
            )
            return None
        if len(name) + len(".") + len(origin) > MAX_NAME_LENGTH:
            logging.warning(
                "Ignoring the name %r of zone %s: the full name would be longer "
                "than %d characters",
                label,
                origin,
                MAX_NAME_LENGTH,
            )
            return None
        if name == NAMESERVER_NAME:
            logging.warning(
                "Ignoring the name %r of zone %s: it belongs to the zone's own "
                "nameserver",
                label,
                origin,
            )
            return None
        return name


def _drop_shared_names(
    addresses: dict[str, set[IpAddress]],
    containers: dict[str, set[str]],
) -> None:
    """Remove the names answering with several addresses of one family.

    A client handed several addresses of a kind reaches whichever one it
    picks, and only one of them may be the one it can reach. Docker gives a
    container one address per family and network, so this is always either two
    containers claiming a name or one container on two networks of one zone.

    A container answering over both families is untouched: those two addresses
    are the same host over two protocols, not a choice between two hosts.
    """
    for name in sorted(addresses):
        found = addresses[name]
        families = Counter(address.version for address in found)
        if all(count == 1 for count in families.values()):
            continue
        logging.warning(
            "Ignoring the name %r entirely: it answers at %s, from %s, and a "
            "client would reach whichever of those it is handed. Set "
            "ALLOW_MULTIPLE_ADDRESSES_PER_NAME to true to publish them all",
            name,
            ", ".join(str(address) for address in sorted(found, key=_address_sort_key)),
            ", ".join(sorted(containers[name])),
        )
        del addresses[name]


def _address_sort_key(address: IpAddress) -> tuple[int, bytes]:
    """Order addresses by family then value, since the two do not compare."""
    return (address.version, address.packed)
