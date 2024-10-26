import logging
import logging.config as logging_config
from pathlib import Path
import sys
from os import getenv
from time import sleep

from daenes.repositories.file_system_zone_repository import FileSystemZoneRepository
from daenes.services.dns_service import DnsService
from daenes.services.docker_service import DockerService


def mgetenv(name: str) -> str:
    """Get an environment variable or exit if it is not set"""
    if (value := getenv(name)) is None:
        logging.critical("Environment variable %s is required", name)
        sys.exit(1)
    return value


class Application:

    __interval: int

    __zone_repository: FileSystemZoneRepository
    __docker_service: DockerService
    __dns_service: DnsService

    def _setup_logging(self) -> None:
        # Configure logging
        log_level = (
            environment_log_level
            if (environment_log_level := getenv("LOG_LEVEL"))
            in logging.getLevelNamesMapping()
            else "INFO"
        )
        logging_config.dictConfig(
            {
                "version": 1,
                "formatters": {
                    "default": {
                        "format": "%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
                    }
                },
                "root": {"level": log_level},
            }
        )

    def _setup(self) -> None:
        """Setup the application"""

        self._setup_logging()

        self.__interval = int(mgetenv("INTERVAL"))

        zones_dir = Path("/zones")
        self.__zone_repository = FileSystemZoneRepository(zones_dir=zones_dir)
        self.__docker_service = DockerService()
        self.__dns_service = DnsService(
            zone_repository=self.__zone_repository,
            dns_ipv4=mgetenv("DNS_IP"),
            ttl=int(mgetenv("DNS_TTL")),
        )

    def _loop(self) -> None:
        """Function called in a loop to check for changes in the forwarded port"""
        domains = list(self.__docker_service.get_local_domains())
        logging.debug("Local domains from docker")
        for domain in domains:
            logging.debug("%s", domain.to_json())
        zones = list(self.__dns_service.make_updated_zones(domains))
        logging.debug("Local DNS zones")
        for zone in zones:
            logging.debug(
                "%s:\n---\n%s\n---",
                zone.get_path().name,
                zone.to_text(want_origin=True),
            )
            self.__zone_repository.save_zone(zone)

    def run(self) -> None:
        """App entry point, in charge of setting up the app and starting the loop"""
        self._setup()
        while True:
            self._loop()
            sleep(self.__interval)


if __name__ == "__main__":
    Application().run()
