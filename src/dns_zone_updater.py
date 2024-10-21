from pathlib import Path

from dns import RecordBuilder, SoaRecord
from local_domain import LocalDomain

# TODO refactor this class

class DnsZoneUpdater:

    __dir: Path
    __dns_ip: str

    def __init__(self, dir_: Path, dns_ip: str):
        self.__dir = dir_
        self.__dns_ip = dns_ip

    def _create_zone(self, local_domain: LocalDomain, serial: int) -> str:
        domain = local_domain.container_domain
        domain_ip = local_domain.ip
        ns = f"ns.{domain}"
        return "\n".join(
            f"$ORIGIN {domain}.",
            f"$TTL 3600",
            RecordBuilder.create_soa_record(domain, serial=serial),
            RecordBuilder.create_ns_record(domain, ns),
            RecordBuilder.create_a_record(ns, self.__dns_ip),
            RecordBuilder.create_a_record(domain, domain_ip),
        )

    def _update_zone_file(self, zone_file: Path, local_domain: LocalDomain):
        """Update a local domain to its zone file"""

        serial = 0

        # If the zone file already exists, increment the serial
        try:
            with zone_file.open("r") as f:
                zone = f.read()
        except FileNotFoundError:
            pass
        else:
            soa_record_text = zone.split("\n")[2]
            soa_record = SoaRecord.from_string(soa_record_text)
            serial = int(soa_record.serial) + 1

        zone = self._create_zone(local_domain, serial)

        with zone_file.open("w") as f:
            f.write(zone)

    def update_zone_files(self, local_domains: list[LocalDomain]) -> None:
        """Update the DNS zones with the local domains"""

        # Create zone files for the local domains
        visited = set[Path]()
        for local_domain in local_domains:
            zone_file = self.__dir / f"{local_domain.container_domain}.zone"
            self._update_zone_file(zone_file, local_domain)
            visited.add(zone_file)

        # Remove zone files that are not in the local domains
        for zone_file in set(self.__dir.glob("*.zone")) - visited:
            zone_file.unlink()
