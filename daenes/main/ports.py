from typing import Protocol

from .model import PublishedNetwork, Zone


class Clock(Protocol):
    """The passage of time, as the application waits on it."""

    def sleep(self, duration: float) -> None: ...


class NetworkSource(Protocol):
    """The deployment being watched, as the zones it asks for.

    An empty list means nothing asks to be published, which is not an error.
    """

    def get_published_networks(self) -> list[PublishedNetwork]: ...


class ZoneStore(Protocol):
    """The zone files a DNS server reads, as the application writes them.

    `get_serial` answers None when there is none to read back, which tells the
    caller to start counting over.
    """

    def get_serial(self, origin: str) -> int | None: ...

    def save(self, zone: Zone) -> None: ...
