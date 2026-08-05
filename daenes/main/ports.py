from typing import Protocol

from .model import PublishedNetwork, Zone


class Clock(Protocol):
    """The passage of time, as the application waits on it."""

    def sleep(self, duration: float) -> None: ...


class NetworkSource(Protocol):
    """The deployment being watched, seen as the zones it asks for.

    Answers what the deployment says, and judges none of it: an empty list
    means nothing asks to be published right now, which is not an error.
    """

    def get_published_networks(self) -> list[PublishedNetwork]: ...


class ZoneStore(Protocol):
    """The zone files a DNS server reads, as the application writes them.

    `get_serial` answers None when no serial can be read back, which is what a
    first run finds, and tells the caller to start counting from the beginning.
    """

    def get_serial(self, origin: str) -> int | None: ...

    def save(self, zone: Zone) -> None: ...
