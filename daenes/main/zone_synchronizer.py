import logging

from .dns_names import MAX_NAME_LENGTH, is_valid_name, normalize
from .model import AddressRecord, AliasRecord, IpAddress, LocalDomain, Zone
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

    Knows nothing of docker or of files: it reads domains through one port and
    writes zones through another.
    """

    def __init__(
        self,
        source: NetworkSource,
        store: ZoneStore,
        nameserver_address: IpAddress,
        ttl: int,
    ) -> None:
        self._source = source
        self._store = store
        self._nameserver_address = nameserver_address
        self._ttl = ttl
        # The last zone written for each origin, so an unchanged zone is left
        # alone rather than rewritten with a new serial, which every secondary
        # server would take for news. Only records can change while the process
        # lives, since the rest of a zone comes from the configuration.
        self._written: dict[str, Zone] = {}

    def synchronize(self) -> None:
        """Bring every zone the deployment describes up to date."""
        for origin, domains in sorted(self._group_by_origin().items()):
            self._synchronize_zone(origin, domains)

    def _group_by_origin(self) -> dict[str, list[LocalDomain]]:
        """Gather the containers by the zone they belong to.

        Two docker networks may deliberately name the same origin, in which
        case their containers land in the same zone.
        """
        grouped: dict[str, list[LocalDomain]] = {}
        for network in self._source.get_published_networks():
            grouped.setdefault(normalize(network.origin), []).extend(network.domains)
        return {
            origin: domains
            for origin, domains in grouped.items()
            if self._is_servable_origin(origin)
        }

    @staticmethod
    def _is_servable_origin(origin: str) -> bool:
        """Whether a zone may be built on this origin, saying why when not."""
        if not is_valid_name(origin):
            logging.error(
                "Ignoring the network asking for %r: a domain is made of labels of "
                "letters, digits and hyphens, and docker names its networks after "
                "the compose project, underscore included",
                origin,
            )
            return False
        if "." not in origin:
            logging.error(
                "Ignoring the network asking for %r: a domain needs more than one "
                "label, did you mean %s.internal?",
                origin,
                origin,
            )
            return False
        return True

    def _synchronize_zone(self, origin: str, domains: list[LocalDomain]) -> None:
        addresses, aliases = self._build_records(origin, domains)
        written = self._written.get(origin)
        if written is not None and (written.addresses, written.aliases) == (
            addresses,
            aliases,
        ):
            logging.debug("Zone %s did not change, leaving it alone", origin)
            return
        zone = Zone(
            origin=origin,
            serial=self._get_next_serial(origin),
            ttl=self._ttl,
            nameserver=NAMESERVER_NAME,
            hostmaster=HOSTMASTER_NAME,
            addresses=addresses,
            aliases=aliases,
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
    ) -> tuple[tuple[AddressRecord, ...], tuple[AliasRecord, ...]]:
        """Turn the domains of one zone into the records it answers with."""
        addresses: dict[str, set[IpAddress]] = {
            NAMESERVER_NAME: {self._nameserver_address}
        }
        aliases: dict[str, set[str]] = {}
        for domain in sorted(domains, key=lambda domain: domain.name):
            name = self._make_name(origin, domain.name, "container")
            if name is None:
                continue
            addresses.setdefault(name, set()).update(domain.addresses)
            for alias in sorted(domain.aliases):
                alias_name = self._make_name(origin, alias, "alias")
                # Docker lists a container's own name among its aliases, and a
                # name pointing at itself is a loop, not an alias.
                if alias_name is None or alias_name == name:
                    continue
                aliases.setdefault(alias_name, set()).add(name)
        return _drop_ambiguous_names(addresses, aliases)

    @staticmethod
    def _make_name(origin: str, label: str, kind: str) -> str | None:
        """The name to write for a container or an alias, or None to skip it."""
        name = normalize(label)
        if not is_valid_name(name):
            logging.warning(
                "Ignoring the %s %r of zone %s: it is not a valid domain name, "
                "give that container a domain of its own instead",
                kind,
                label,
                origin,
            )
            return None
        if len(name) + len(".") + len(origin) > MAX_NAME_LENGTH:
            logging.warning(
                "Ignoring the %s %r of zone %s: the full name would be longer "
                "than %d characters",
                kind,
                label,
                origin,
                MAX_NAME_LENGTH,
            )
            return None
        if name == NAMESERVER_NAME:
            logging.warning(
                "Ignoring the %s %r of zone %s: that name belongs to the zone's "
                "own nameserver",
                kind,
                label,
                origin,
            )
            return None
        return name


def _drop_ambiguous_names(
    addresses: dict[str, set[IpAddress]],
    aliases: dict[str, set[str]],
) -> tuple[tuple[AddressRecord, ...], tuple[AliasRecord, ...]]:
    """Remove the names a DNS server could not answer for without choosing.

    An alias sharing its name with an address, or pointing at two different
    names, has no defensible answer, and RFC 2181 section 10.1 forbids the
    first outright. Neither reading is published: guessing which container the
    deployment meant is not ours to do.
    """
    for name in sorted(set(aliases) & set(addresses)):
        logging.warning(
            "Ignoring the name %r entirely: it is both an address and an alias of %s",
            name,
            ", ".join(sorted(aliases[name])),
        )
        del aliases[name]
        del addresses[name]
    for name, targets in sorted(aliases.items()):
        if len(targets) > 1:
            logging.warning(
                "Ignoring the alias %r entirely: it points at %s at once",
                name,
                " and ".join(sorted(targets)),
            )
            del aliases[name]
    return (
        tuple(
            AddressRecord(name=name, addresses=tuple(sorted(found, key=_sort_key)))
            for name, found in sorted(addresses.items())
        ),
        tuple(
            AliasRecord(name=name, target=next(iter(targets)))
            for name, targets in sorted(aliases.items())
        ),
    )


def _sort_key(address: IpAddress) -> tuple[int, bytes]:
    """Order addresses by family then value, since the two do not compare."""
    return (address.version, address.packed)
