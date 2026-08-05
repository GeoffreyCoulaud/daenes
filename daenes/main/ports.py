from typing import Protocol

from .model import PublishedNetwork, Zone


class ChangeNotifier(Protocol):
    """The deployment saying it changed, as the application waits on it.

    Answers True when something may have changed, False when the wait ran out.
    May, not did: waking for nothing costs a pass that writes nothing, while
    staying silent over a real change is the one thing a notifier may not do.
    """

    def wait_for_change(self, timeout: float) -> bool: ...


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
