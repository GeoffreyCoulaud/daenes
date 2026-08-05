import logging
from collections.abc import Iterator
from ipaddress import ip_address
from typing import Any

from docker.client import DockerClient
from docker.errors import DockerException
from docker.models.containers import Container
from docker.models.networks import Network
from requests.exceptions import RequestException

from .errors import RetryableError
from .model import IpAddress, LocalDomain, PublishedNetwork

DOMAIN_LABEL = "daenes.domain"
ENABLED_LABEL = "daenes.enabled"

# The keys docker answers a container's addresses on a network with. Both may
# be empty: a container gets the second one only on a network carrying IPv6.
ADDRESS_KEYS = ("IPAddress", "GlobalIPv6Address")


class DockerUnreachable(RetryableError):
    """Raised when the docker daemon cannot be questioned right now."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args, "Failed to question the docker daemon")


class DockerStartupError(Exception):
    """Raised when the docker daemon does not answer at startup at all."""

    def __init__(self, *args: object) -> None:
        super().__init__(
            *args,
            "Could not reach the docker daemon. "
            "Check that /var/run/docker.sock is mounted.",
        )


def connect() -> DockerClient:
    """Connect to the docker daemon, and make sure it is really answering.

    Creating a client proves nothing on its own, so the daemon is pinged here:
    a socket that was never mounted is a mistake in the deployment, and saying
    so at startup beats failing on the first turn of the loop.
    """
    try:
        client = DockerClient.from_env()
        client.ping()
    except (DockerException, RequestException) as error:
        raise DockerStartupError() from error
    logging.debug("Connected to the docker daemon")
    return client


class DockerDomainSource:
    """The deployment, seen through the docker API.

    Reports what docker says and judges none of it: which of these names can
    be served is decided where the zone is built.
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

        One listing, filtered here rather than by the daemon, so that a network
        left with nothing but the daenes.enabled label of earlier versions can
        be reported instead of passed over in silence.
        """
        published: list[Network] = []
        for network in self._client.networks.list():
            labels = _get_labels(network)
            if DOMAIN_LABEL in labels:
                published.append(network)
            elif ENABLED_LABEL in labels:
                logging.warning(
                    "Ignoring network %s: it carries a %s label but no %s label. "
                    "Since daenes 1.0.0 a network is published by naming the zone "
                    "it publishes, for instance %s=services.internal",
                    network.name,
                    ENABLED_LABEL,
                    DOMAIN_LABEL,
                    DOMAIN_LABEL,
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
        name = _get_name(container)
        # A container may have left the network since it was listed.
        settings = container.attrs["NetworkSettings"]["Networks"].get(network.name)
        if settings is None:
            logging.debug("Container %s left network %s", name, network.name)
            return None
        addresses = tuple(_get_addresses(settings))
        if not addresses:
            logging.debug("Container %s has no address on %s", name, network.name)
            return None
        return LocalDomain(
            container=container.short_id,
            name=name,
            addresses=addresses,
            aliases=frozenset(settings.get("Aliases") or ()),
        )


def _get_labels(network: Network) -> dict[str, str]:
    """The labels of a network, which docker answers as null when it has none."""
    return network.attrs.get("Labels") or {}


def _is_enabled(container: Container) -> bool:
    """Whether a container on a published network wants to be published.

    Containers are in by default, which is the whole point of reading a
    deployment rather than being told about it, and opt out explicitly.
    """
    return container.labels.get(ENABLED_LABEL, "true") == "true"


def _get_name(container: Container) -> str:
    """The name a container asks for, its own unless a label says otherwise.

    Docker names every container it answers a full inspect for, so the last
    fallback stands for nothing it has ever said. It is there so that a
    container arriving without a name would be left out by the name rules,
    the way any other unservable name is, rather than taken for a crash.
    """
    return container.labels.get(DOMAIN_LABEL) or container.name or ""


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
