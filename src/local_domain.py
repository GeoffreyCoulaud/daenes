from dataclasses import dataclass


@dataclass
class LocalDomain:

    container_id: str
    domain: str
    ipv4: str
