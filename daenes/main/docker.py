import logging
from collections.abc import Iterator
from ipaddress import ip_address
from typing import Any, cast

from docker.client import DockerClient
from docker.errors import DockerException
from docker.models.containers import Container
from docker.models.networks import Network
from docker.utils import version_lt
from requests.exceptions import RequestException

from .errors import ReturnCodes, RetryableError
from .model import IpAddress, LocalDomain, PublishedNetwork

# The label a network publishes a zone with, and the one a container opts out
# with. A container is named by docker alone.
DOMAIN_LABEL = "daenes.domain"
ENABLED_LABEL = "daenes.enabled"

# Every name docker answers for a container on a network: its own name, its
# hostname, and its aliases. Introduced in API 1.44, which is docker 25.0.
DNS_NAMES_KEY = "DNSNames"
MINIMUM_API_VERSION = "1.44"
MINIMUM_DOCKER_VERSION = "25.0"

# Where docker puts a container's addresses on a network. Either may be empty:
# the second one only exists on a network carrying IPv6.
ADDRESS_KEYS = ("IPAddress", "GlobalIPv6Address")

# Docker-py answers no name for an object it read only in part. Everything here
# is read in full, hence the casts below.


class DockerUnreachable(RetryableError):
    """Raised when the docker daemon cannot be questioned right now."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args, "Failed to question the docker daemon")


class DockerStartupError(Exception):
    """Raised when the daemon cannot be used, whichever way it cannot.

    Carries the exit code to stop on, since what to do about it depends on
    which of the two it is.
    """

    def __init__(self, return_code: ReturnCodes, message: str) -> None:
        super().__init__(message)
        self.return_code = return_code


def connect() -> DockerClient:
    """Connect to the docker daemon, and check it is one daenes can read.

    Creating a client proves nothing on its own, so a socket that was never
    mounted, and a daemon too old to say what it calls its containers, are both
    worth finding here rather than on the first turn of the loop.
    """
    try:
        client = DockerClient.from_env()
        version = client.version()["ApiVersion"]
    except (DockerException, RequestException, KeyError) as error:
        raise DockerStartupError(
            ReturnCodes.DOCKER_UNREACHABLE_AT_STARTUP,
            "Could not reach the docker daemon. "
            "Check that /var/run/docker.sock is mounted.",
        ) from error
    if version_lt(version, MINIMUM_API_VERSION):
        raise DockerStartupError(
            ReturnCodes.DOCKER_TOO_OLD,
            f"This docker daemon speaks API {version}, and daenes needs "
            f"{MINIMUM_API_VERSION} or newer, which is docker "
            f"{MINIMUM_DOCKER_VERSION} or newer.",
        )
    logging.debug("Connected to a docker daemon speaking API %s", version)
    return client


class DockerDomainSource:
    """The deployment, seen through the docker API.

    Reports what docker says and judges none of it: which of these names can be
    served is decided where the zone is built.
    """

    def __init__(self, client: DockerClient) -> None:
        self._client = client

    def get_published_networks(self) -> list[PublishedNetwork]:
        try:
            return list(self._collect_published_networks())
        except (DockerException, RequestException) as error:
            raise DockerUnreachable() from error

    def _collect_published_networks(self) -> Iterator[PublishedNetwork]:
        for network in self._get_labelled_networks():
            # Listing networks answers without their containers; only an
            # inspect carries them.
            network.reload()
            origin = _get_labels(network)[DOMAIN_LABEL]
            logging.debug("Network %s publishes zone %s", network.name, origin)
            yield PublishedNetwork(
                name=cast(str, network.name),
                origin=origin,
                domains=tuple(self._get_local_domains(network)),
            )

    def _get_local_domains(self, network: Network) -> Iterator[LocalDomain]:
        for container in network.containers:
            domain = self._get_local_domain(container, network)
            if domain is not None:
                yield domain

    def _get_labelled_networks(self) -> list[Network]:
        """The networks a daenes.domain label asks to publish.

        Filtered here rather than by the daemon, so that a network left with
        only the daenes.enabled label of earlier versions can be reported.
        """
        published: list[Network] = []
        for network in self._client.networks.list():
            labels = _get_labels(network)
            if DOMAIN_LABEL in labels:
                published.append(network)
            elif ENABLED_LABEL in labels:
                logging.warning(
                    "Ignoring network %s: since daenes 1.0.0 a network is "
                    "published by %s=<domain>, not by %s",
                    network.name,
                    DOMAIN_LABEL,
                    ENABLED_LABEL,
                )
        return published

    @staticmethod
    def _get_local_domain(
        container: Container,
        network: Network,
    ) -> LocalDomain | None:
        """What one container asks to publish on one network, if anything."""
        if not _is_enabled(container):
            logging.debug("Container %s opted out of daenes", container.name)
            return None
        name = cast(str, container.name)
        # A container may have left the network since it was listed.
        settings = container.attrs["NetworkSettings"]["Networks"].get(network.name)
        if settings is None:
            logging.debug("Container %s left network %s", name, network.name)
            return None
        addresses = tuple(_get_addresses(settings))
        if not addresses:
            logging.debug("Container %s has no address on %s", name, network.name)
            return None
        names = _get_names(settings, container.short_id)
        if not names:
            logging.debug("Container %s answers to no name on %s", name, network.name)
            return None
        return LocalDomain(
            container=container.short_id,
            names=names,
            addresses=addresses,
        )


def _get_labels(network: Network) -> dict[str, str]:
    """The labels of a network, which docker answers as an empty map when none.

    Falling back rather than reading the key straight: Go serialises a map it
    never allocated as null, and an older daemon may well do just that.
    """
    return network.attrs.get("Labels") or {}


def _is_enabled(container: Container) -> bool:
    """Whether a container wants publishing, which it does unless it says no."""
    return container.labels.get(ENABLED_LABEL, "true") == "true"


def _get_names(settings: dict[str, Any], short_id: str) -> frozenset[str]:
    """Every name docker answers for a container on one network.

    Its identifier is one of them, and is left out: it is a name for the daemon
    to know a container by, not one anybody types, and it changes on every
    redeploy. A container given no hostname is given that identifier as one,
    which the same comparison drops.
    """
    return frozenset(settings.get(DNS_NAMES_KEY) or ()) - {short_id}


def _get_addresses(settings: dict[str, Any]) -> Iterator[IpAddress]:
    """The addresses a container answers on, over both families."""
    for key in ADDRESS_KEYS:
        value = settings.get(key)
        if not value:
            continue
        try:
            yield ip_address(value)
        except ValueError:
            logging.warning("Docker gave %r as an address, ignoring it", value)
