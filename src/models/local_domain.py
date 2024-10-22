from dataclasses import dataclass
import json
from typing import Iterable


@dataclass
class LocalDomain:
    parent: str
    domain: str
    ipv4: str

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__)


@dataclass
class LocalDomainGroup:
    parent: str
    domains: Iterable[LocalDomain]
