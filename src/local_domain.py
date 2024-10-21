from dataclasses import dataclass
import json


@dataclass
class LocalDomain:
    network_domain: str
    container_domain: str
    container_ipv4: str

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__)
