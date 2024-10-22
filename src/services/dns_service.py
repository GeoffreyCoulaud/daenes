from itertools import groupby
import logging
from pathlib import Path
from typing import Generator, Iterable

from dns.zone import Zone, from_file as zone_from_file
from dns.rdataclass import IN
from dns.name import from_text as name_from_text
from dns.rdtypes.ANY.SOA import SOA
from dns.rdtypes.ANY.NS import NS
from dns.rdtypes.IN.A import A
from dns import rdatatype

from models.local_domain import LocalDomain, LocalDomainGroup


class InvalidSubdomainError(Exception):
    """Raised when a subdomain is not a valid subdomain of a domain"""


class DnsService:

    __zone_files_dir: Path
    __dns_ip: str

    __ttl: int

    def __init__(self, zone_files_dir: Path, dns_ipv4: str, ttl: int = 3600):
        self.__zone_files_dir = zone_files_dir
        self.__dns_ip = dns_ipv4
        self.__ttl = ttl

    def _make_zone(self, domain_group: LocalDomainGroup, serial: int = 0) -> Zone:

        parent = domain_group.parent
        domains = domain_group.domains

        zone_name = name_from_text(f"{parent}.")
        ns_name = name_from_text(f"ns.{parent}.")
        zone = Zone(origin=zone_name)

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
        for domain in [d for d in domains if d.domain == "ns"]:
            raise InvalidSubdomainError("Cannot have a subdomain named 'ns'")
        domains_including_ns = list(domains)
        domains_including_ns.append(LocalDomain(parent, "ns", self.__dns_ip))

        # Data for other subdomains
        for domain in domains:
            domain_name = name_from_text(f"{domain.domain}.{parent}.")
            zone_domain_node = zone.find_node(domain_name, create=True)
            # A record
            a_rdata = A(IN, rdatatype.A, domain.ipv4)
            a_rdataset = zone_domain_node.find_rdataset(IN, rdatatype.A, create=True)
            a_rdataset.update_ttl(self.__ttl)
            a_rdataset.add(a_rdata)

    def _update_zone(self, domain_group: LocalDomainGroup):
        path = self.__zone_files_dir / f"{domain_group.parent}.zone"
        try:
            serial = zone_from_file(str(path), check_origin=True).get_soa().serial
        except Exception as error:
            logging.warning("Couldn't find zone current serial", exc_info=error)
            serial = 0
        zone = self._make_zone(domain_group=domain_group, serial=serial + 1)
        zone.to_file(str(path), relativize=False)

    def _group_local_domains(
        self, domains: Iterable[LocalDomain]
    ) -> Generator[LocalDomainGroup, None, None]:
        for parent, domains in groupby(domains, lambda d: d.parent):
            yield LocalDomainGroup(parent=parent, domains=domains)

    def update_zones(self, domains: Iterable[LocalDomain]) -> None:
        for domain_group in self._group_local_domains(domains=domains):
            self._update_zone(domain_group=domain_group)

    def get_zones(self) -> Generator[Zone, None, None]:
        for path in self.__zone_files_dir.glob("*.zone"):
            yield zone_from_file(str(path))
