from functools import partial
from itertools import groupby
import logging
from pathlib import Path
from typing import Any, Generator, Iterable, Protocol

import dns
from dns.zone import Zone, from_file as zone_from_file
from dns.rdataclass import IN, RdataClass
from dns.name import Name, from_text as name_from_text
from dns.rdtypes.ANY.SOA import SOA
from dns.rdtypes.ANY.NS import NS
from dns.rdtypes.IN.A import A
from dns import rdatatype

from models.local_domain import LocalDomain


class InvalidSubdomainError(Exception):
    """Raised when a subdomain is not a valid subdomain of a domain"""


class ZoneFactory(Protocol):

    def __call__(
        self,
        origin: Name | str | None,
        rdclass: RdataClass = dns.rdataclass.IN,
    ) -> Zone: ...


class FileSystemZone(Zone):

    __path: Path

    def __init__(
        self,
        path: Path,
        origin: Name | str | None,
        rdclass: RdataClass = dns.rdataclass.IN,
        relativize: bool = True,
    ) -> None:
        super().__init__(origin, rdclass, relativize)
        self.__path = path

    def get_path(self) -> Path:
        """Get the path of the zone file"""
        return self.__path

    def to_file(
        self,
        f: Any = None,
        sorted: bool = True,
        relativize: bool = True,
        nl: str | None = None,
        want_comments: bool = True,
        want_origin: bool = True,
    ) -> None:
        # Only use the override if provided
        f = f if f is not None else str(self.__path)
        # Write to disk
        return super().to_file(
            f=f,
            sorted=sorted,
            relativize=relativize,
            nl=nl,
            want_comments=want_comments,
            want_origin=want_origin,
        )


class DnsService:

    __zone_files_dir: Path
    __dns_ip: str
    __ttl: int

    def __init__(self, zone_files_dir: Path, dns_ipv4: str, ttl: int = 3600):
        self.__zone_files_dir = zone_files_dir
        self.__dns_ip = dns_ipv4
        self.__ttl = ttl

    def _make_zone(
        self,
        parent: str,
        domains: Iterable[LocalDomain],
        previous_zone: Zone | None,
        zone_factory: ZoneFactory = Zone,
    ) -> Zone:

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
        domains_including_ns = list(domains)
        for domain in [d for d in domains if d == "ns"]:
            raise InvalidSubdomainError("Cannot have a subdomain named 'ns'")
        domains_including_ns.append(LocalDomain(parent, "ns", self.__dns_ip))

        # Data for other subdomains
        for domain in domains_including_ns:
            logging.debug("Including %s subdomain in %s zone", domain.domain, parent)
            domain_name = name_from_text(f"{domain.domain}.{parent}.")
            zone_domain_node = zone.find_node(domain_name, create=True)
            # A record
            a_rdata = A(IN, rdatatype.A, domain.ipv4)
            a_rdataset = zone_domain_node.find_rdataset(IN, rdatatype.A, create=True)
            a_rdataset.update_ttl(self.__ttl)
            a_rdataset.add(a_rdata)

        return zone

    def make_updated_zones(
        self, domains: Iterable[LocalDomain]
    ) -> Generator[FileSystemZone, None, None]:
        for parent, domains in groupby(domains, lambda d: d.parent):
            path = self.__zone_files_dir / f"{parent}.zone"
            try:
                previous_zone = zone_from_file(str(path))
            except Exception:
                logging.warning("Could not find existing zone at %s", str(path))
                previous_zone = None
            yield self._make_zone(
                parent=parent,
                domains=domains,
                previous_zone=previous_zone,
                zone_factory=partial(FileSystemZone, path=path),
            )
