from abc import ABC

from dns.zone import Zone

from models.file_system_zone import ZoneFactoryKwargs


class ZoneRepository(ABC):
    """Base zone repositoy"""

    def find_zone(self, parent: str) -> Zone:
        """Try to find a persisted zone, returns None if missing"""

    def create_zone(self, parent: str, **zone_kwargs: ZoneFactoryKwargs) -> Zone:
        """Create a persistable zone"""
