from dataclasses import dataclass, field
import json


@dataclass
class LocalDomain:

    # Required fields
    parent: str
    name: str
    ip: str

    # Optional fields
    aliases: set[str] = field(default_factory=set)

    def to_json(self) -> str:
        return json.dumps(
            {
                "parent": self.parent,
                "name": self.name,
                "aliases": list(self.aliases),
                "ip": self.ip,
            }
        )
