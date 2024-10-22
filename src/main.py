import logging
import logging.config as logging_config
import sys
from os import getenv
from time import sleep

from services.dns import DnsService
from services.docker import DockerService


def mgetenv(name: str) -> str:
    """Get an environment variable or exit if it is not set"""
    if (value := getenv(name)) is None:
        logging.critical("Environment variable %s is required", name)
        sys.exit(1)
    return value


class Application:

    __sleep_on_success: int
    __sleep_on_error: int
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
        self.__sleep_on_success = int(mgetenv("SLEEP_ON_SUCCESS"))
        self.__sleep_on_error = int(mgetenv("SLEEP_ON_ERROR"))
        self.__docker_service = DockerService()
        self.__dns_service = DnsService(
            zone_files_dir=mgetenv("DNS_ZONE_FILES_DIR"),
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
            logging.debug("%s:\n%s", zone.get_path().name, zone.to_text())
            zone.to_file()

    def run(self) -> None:
        """App entry point, in charge of setting up the app and starting the loop"""
        self._setup()
        while True:
            # TODO error handling
            self._loop()
            sleep(self.__sleep_on_success)


if __name__ == "__main__":
    Application().run()
