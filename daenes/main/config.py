from dataclasses import dataclass
from ipaddress import ip_address
from os import getenv
from pathlib import Path

from .errors import ReturnCodes
from .model import IpAddress

DEFAULT_ZONES_DIRECTORY = "/zones"
DEFAULT_TTL = 60
DEFAULT_SUCCESS_INTERVAL = 60
DEFAULT_RETRY_INTERVAL = 10


class ConfigurationError(Exception):
    """Raised when the environment does not describe a usable setup.

    Carries the exit code to stop on, since a mistake in the environment is
    reported to whoever started the container rather than retried.
    """

    def __init__(self, return_code: ReturnCodes, message: str) -> None:
        super().__init__(message)
        self.return_code = return_code


@dataclass(frozen=True)
class Config:
    zones_directory: Path
    nameserver_address: IpAddress
    ttl: int
    success_interval: int
    retry_interval: int


def _get_required(name: str) -> str:
    """Read an environment variable that has no sensible default."""
    if (value := getenv(name)) is None:
        raise ConfigurationError(
            ReturnCodes.MISSING_ENVIRONMENT_VARIABLE,
            f"Environment variable {name} is required",
        )
    return value


def _get_integer(name: str, default: int, minimum: int) -> int:
    """Read a whole number of seconds, refusing one that makes no sense."""
    if (value := getenv(name)) is None:
        return default
    try:
        number = int(value)
    except ValueError as error:
        raise ConfigurationError(
            ReturnCodes.INVALID_ENVIRONMENT_VARIABLE,
            f"Environment variable {name} must be an integer, got {value!r}",
        ) from error
    if number < minimum:
        raise ConfigurationError(
            ReturnCodes.INVALID_ENVIRONMENT_VARIABLE,
            f"Environment variable {name} must be {minimum} or more, got {number}",
        )
    return number


def _get_nameserver_address() -> IpAddress:
    """Read the address of the DNS server the zones name as their own."""
    value = _get_required("DNS_IP")
    try:
        return ip_address(value)
    except ValueError as error:
        raise ConfigurationError(
            ReturnCodes.INVALID_ENVIRONMENT_VARIABLE,
            f"Environment variable DNS_IP must be an IP address, got {value!r}",
        ) from error


def get_configuration() -> Config:
    """Read the whole environment, or raise ConfigurationError."""
    return Config(
        zones_directory=Path(getenv("ZONES_DIR", DEFAULT_ZONES_DIRECTORY)),
        nameserver_address=_get_nameserver_address(),
        # A TTL of zero is legal, and tells resolvers not to cache at all.
        ttl=_get_integer("DNS_TTL", DEFAULT_TTL, minimum=0),
        success_interval=_get_integer(
            "SUCCESS_INTERVAL", DEFAULT_SUCCESS_INTERVAL, minimum=1
        ),
        retry_interval=_get_integer(
            "RETRY_INTERVAL", DEFAULT_RETRY_INTERVAL, minimum=1
        ),
    )
