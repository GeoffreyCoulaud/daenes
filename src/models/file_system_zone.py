from pathlib import Path
from typing import Any, Protocol, TypedDict

import dns
from dns.zone import Zone
from dns.rdataclass import RdataClass
from dns.name import Name


class ZoneFactoryKwargs(TypedDict):
    origin: Name | str | None
    rdclass: RdataClass = dns.rdataclass.IN


class ZoneFactory(Protocol):

    def __call__(self, **kwargs: ZoneFactoryKwargs) -> Zone: ...


class FileSystemZone(Zone):

    __path: Path

    def __init__(
        self,
        path: Path,
        origin: Name | str | None,
        rdclass: RdataClass = dns.rdataclass.IN,
        relativize: bool = True,
    ) -> None:
        super().__init__(origin, rdclass, relativize)
        self.__path = path

    def get_path(self) -> Path:
        """Get the path of the zone file"""
        return self.__path
