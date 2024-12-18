from functools import partial
from itertools import groupby
import logging

from dns.zone import Zone
from dns.rdataclass import IN
from dns.name import from_text as name_from_text
from dns.rdtypes.ANY.SOA import SOA
from dns.rdtypes.ANY.NS import NS
from dns.rdtypes.IN.A import A
from dns.rdtypes.IN.AAAA import AAAA
from dns.rdtypes.ANY.CNAME import CNAME
from dns import rdatatype

from daenes.models.file_system_zone import ZoneFactory
from daenes.models.local_domain import LocalDomain
from daenes.repositories.zone_repository import ZoneRepository


class InvalidSubdomainError(Exception):
    """Raised when a subdomain is not a valid subdomain of a domain"""


class DuplicateSubdomainError(Exception):
    """Raised when a subdomain is already present in a domain"""


class DnsService:

    __zone_repository: ZoneRepository
    __dns_ip: str
    __ttl: int

    def __init__(
        self,
        zone_repository: ZoneRepository,
        dns_ipv4: str,
        ttl: int = 3600,
    ):
        self.__zone_repository = zone_repository
        self.__dns_ip = dns_ipv4
        self.__ttl = ttl

    def _make_zone(
        self,
        parent: str,
        domains: list[LocalDomain],
        previous_zone: Zone | None,
        zone_factory: ZoneFactory = Zone,
    ) -> Zone:
        # pylint: disable=too-many-locals

        serial = 1 + (-1 if previous_zone is None else previous_zone.get_soa().serial)
        zone_name = name_from_text(f"{parent}.")
        ns_name = name_from_text(f"ns.{parent}.")
        zone = zone_factory(origin=zone_name)

        # Data for "parent" domain
        parent_node = zone.find_node(zone_name, create=True)

        parent_soa_rdata = SOA(
            rdclass=IN,
            rdtype=rdatatype.SOA,
            mname=ns_name,
            rname=name_from_text(f"admin.{parent}."),
            serial=serial,
            refresh=3600,
            retry=600,
            expire=604800,
            minimum=600,
        )
        parent_soa_rdataset = parent_node.find_rdataset(IN, rdatatype.SOA, create=True)
        parent_soa_rdataset.update_ttl(self.__ttl)
        parent_soa_rdataset.add(parent_soa_rdata)

        parent_ns_rdata = NS(IN, rdatatype.NS, ns_name)
        parent_ns_rdataset = parent_node.find_rdataset(IN, rdatatype.NS, create=True)
        parent_ns_rdataset.update_ttl(self.__ttl)
        parent_ns_rdataset.add(parent_ns_rdata)

        # Add an additional NS subdomain
        domains_including_ns = [
            *domains,
            LocalDomain(parent=parent, name="ns", ip=self.__dns_ip),
        ]

        # Data for other subdomains
        seen_names = set[str]()
        for domain in domains_including_ns:

            # Ensure no conflicting subdomains (should not happen, but just in case)
            for name in [domain.name, *domain.aliases]:
                if name in seen_names:
                    msg = f"Duplicate subdomain in {parent}: {name}"
                    raise DuplicateSubdomainError(msg)
                seen_names.add(name)

            logging.debug("Including %s subdomain in %s zone", domain.name, parent)
            domain_name = name_from_text(f"{domain.name}.{parent}.")
            domain_node = zone.find_node(domain_name, create=True)

            # A / AAAA record
            if ":" in domain.ip:
                a_rdatatype = rdatatype.AAAA
                a_rdata = AAAA(IN, rdatatype.AAAA, domain.ip)
            else:
                a_rdatatype = rdatatype.A
                a_rdata = A(IN, rdatatype.A, domain.ip)
            a_rdataset = domain_node.find_rdataset(IN, a_rdatatype, create=True)
            a_rdataset.update_ttl(self.__ttl)
            a_rdataset.add(a_rdata)

            # CNAME for aliases
            for alias in domain.aliases:
                logging.debug("Including alias %s in %s zone", alias, parent)
                alias_name = name_from_text(f"{alias}.{parent}.")
                alias_node = zone.find_node(name=alias_name, create=True)
                cname_rdata = CNAME(IN, rdatatype.CNAME, domain_name)
                cname_rdataset = alias_node.find_rdataset(
                    IN, rdatatype.CNAME, create=True
                )
                cname_rdataset.update_ttl(self.__ttl)
                cname_rdataset.add(cname_rdata)

        return zone

    def make_updated_zones(self, domains: list[LocalDomain]) -> list[Zone]:
        zones = []
        for parent, siblings in groupby(domains, lambda d: d.parent):
            previous_zone = self.__zone_repository.find_zone(parent)
            if previous_zone is not None:
                logging.debug("Found previous zone for %s", parent)
            else:
                logging.debug("No previous zone for %s", parent)
            zone = self._make_zone(
                parent=parent,
                domains=list(siblings),
                previous_zone=previous_zone,
                zone_factory=partial(
                    self.__zone_repository.create_zone,
                    parent=parent,
                ),
            )
            zones.append(zone)
        return zones
