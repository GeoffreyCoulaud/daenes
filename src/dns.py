from dataclasses import dataclass
import re


@dataclass
class SoaRecord:

    domain: str
    serial: int
    refresh: int
    retry: int
    expire: int
    minimum_ttl: int

    def to_string(self) -> str:
        return " ".join(
            f"{self.domain}.",
            "IN",
            "SOA",
            f"ns.{self.domain}.",
            f"admin.{self.domain}.",
            "(",
            f"{self.serial}",
            f"{self.refresh}",
            f"{self.retry}",
            f"{self.expire}",
            f"{self.minimum_ttl}",
            ")",
        )

    @classmethod
    def from_string(cls, soa_record: str) -> "SoaRecord":
        """
        Create a SoaRecord from a string

        Notes:
        - Whitespace should be minimal, **multiple spaces are not allowed**
        - The SOA record format is:
            <domain>. IN SOA <ns>. <mail>. (<serial> <refresh> <retry> <expire> <minimum_ttl>)
        """

        # Use a regex with named groups to parse the SOA record
        regex = re.compile(
            r"^(?P<domain>\S+)\. IN SOA (?P<ns>\S+)\. (?P<mail>\S+)\. \((?P<serial>\d+) (?P<refresh>\d+) (?P<retry>\d+) (?P<expire>\d+) (?P<minimum_ttl>\d+)\)$"
        )
        match = regex.match(soa_record)

        # Use the named groups to create the SoaRecord
        try:
            groups = match.groupdict()
            return cls(
                domain=groups["domain"],
                serial=int(groups["serial"]),
                refresh=int(groups["refresh"]),
                retry=int(groups["retry"]),
                expire=int(groups["expire"]),
                minimum_ttl=int(groups["minimum_ttl"]),
            )
        except AttributeError:
            raise ValueError("Invalid SOA record format")
        except KeyError:
            raise ValueError("Missing required fields in SOA record")
        except ValueError:
            raise ValueError("Invalid integer value in SOA record")


class RecordBuilder:

    @classmethod
    def create_soa_record(
        cls,
        domain: str,
        *,
        serial: int = 0,
        refresh: int = 3600,
        retry: int = 600,
        expire: int = 604800,
        minimum_ttl: int = 86400,
    ) -> str:
        """Create a SOA record for a domain"""
        return SoaRecord(
            domain=domain,
            serial=str(serial),
            refresh=str(refresh),
            retry=str(retry),
            expire=str(expire),
            minimum_ttl=str(minimum_ttl),
        ).to_string()

    @classmethod
    def create_ns_record(cls, domain: str, ns: str) -> str:
        """Create a NS record for a domain"""
        return f"{domain}. IN NS {ns}."

    @classmethod
    def create_a_record(cls, domain: str, ip: str) -> str:
        """Create an A record for a domain"""
        return f"{domain}. IN A {ip}"

    @classmethod
    def create_txt_record(cls, domain: str, text: str) -> str:
        """Create a TXT record for a domain"""
        return f'{domain}. IN TXT "{text}"'
