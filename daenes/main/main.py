import logging
import logging.config as logging_config
import signal
import sys
from os import getenv

from docker.client import DockerClient

from .application import Application
from .clock import SystemClock
from .config import Config, ConfigurationError, get_configuration
from .docker import DockerDomainSource, DockerStartupError, connect
from .errors import ReturnCodes
from .zone_files import FileSystemZoneStore
from .zone_synchronizer import ZoneSynchronizer


def configure_logging() -> None:
    """Configure logging from the LOG_LEVEL environment variable"""
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
                },
            },
            "loggers": {
                # One line per call to the daemon, which is a lot of them.
                "urllib3": {
                    "level": "DEBUG" if log_level == "DEBUG" else "WARNING",
                },
            },
            "root": {
                "level": log_level,
            },
        }
    )
    logging.basicConfig(
        level=log_level, format="%(asctime)s [%(levelname)s] %(message)s"
    )


def build_application(config: Config, client: DockerClient) -> Application:
    """Wire every part together, which happens here and nowhere else."""
    return Application(
        synchronizer=ZoneSynchronizer(
            source=DockerDomainSource(client=client),
            store=FileSystemZoneStore(directory=config.zones_directory),
            nameserver_address=config.nameserver_address,
            ttl=config.ttl,
            allowances=config.allowances,
        ),
        clock=SystemClock(),
        retry_interval=config.retry_interval,
        success_interval=config.success_interval,
    )


def handle_sigterm(*_: object) -> None:
    """Shut down on SIGTERM, which is how docker stops a container.

    Without a handler the kernel never delivers it to PID 1, and `docker stop`
    waits out its whole timeout before resorting to SIGKILL.
    """
    logging.info("Received SIGTERM, shutting down")
    sys.exit(0)


def main() -> None:
    """Run the application, and turn whatever stops it into an exit code."""
    signal.signal(signal.SIGTERM, handle_sigterm)
    configure_logging()
    try:
        config = get_configuration()
        build_application(config, connect()).run()
    except ConfigurationError as error:
        logging.critical("%s", error)
        sys.exit(error.return_code)
    except DockerStartupError as error:
        logging.critical("%s", error)
        logging.debug("The daemon could not be reached", exc_info=error)
        sys.exit(ReturnCodes.DOCKER_UNREACHABLE_AT_STARTUP)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.critical("Unretryable error in lifecycle", exc_info=error)
        sys.exit(ReturnCodes.UNRETRYABLE_EXCEPTION_IN_LIFECYCLE)
