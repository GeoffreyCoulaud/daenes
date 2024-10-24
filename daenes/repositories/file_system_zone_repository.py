import logging
from pathlib import Path

from dns.zone import Zone, from_file as zone_from_file

from daenes.repositories.zone_repository import ZoneRepository
from daenes.models.file_system_zone import FileSystemZone, ZoneFactoryKwargs


class FileSystemZoneRepository(ZoneRepository):

    __zones_dir: Path

    def __init__(self, zones_dir: str | Path) -> None:
        self.__zones_dir = Path(zones_dir)

    def _get_zone_path(self, parent: str) -> Path:
        return self.__zones_dir / f"{parent}.zone"

    def find_zone(self, parent: str) -> None | Zone:
        try:
            return zone_from_file(self._get_zone_path(parent))
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def create_zone(
        self,
        parent: str,
        **zone_kwargs: ZoneFactoryKwargs,
    ) -> FileSystemZone:
        return FileSystemZone(
            path=self._get_zone_path(parent),
            **zone_kwargs,
        )

    def save_zone(self, zone: FileSystemZone) -> None:
        path = zone.get_path()
        logging.debug("Saving zone to %s", path)
        zone_text = zone.to_text(
            sorted=True,
            relativize=True,
            want_comments=True,
            want_origin=True,
        )
        with path.open("w", encoding="utf-8") as f:
            f.write(zone_text)
