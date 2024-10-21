import logging
from typing import Generator
from docker.client import DockerClient
from docker.models.containers import Container
from docker.models.networks import Network

from constants import PROJECT
from local_domain import LocalDomain


class MissingNetworkDomainLabel(Exception):
    """Exception raised when the network domain label is missing"""


class DockerLabelObserver:

    __container_enabled_label: str
    __container_domain_label: str
    __network_enabled_label: str
    __network_domain_label: str

    __client: DockerClient = None

    def _create_label(self, label: str) -> str:
        """Create a docker label prefixed by the project name and the domain name"""
        return f"{PROJECT}.{label}"

    def __init__(self) -> None:
        self.__container_domain_label = self._create_label("domain")
        self.__container_enabled_label = self._create_label("enabled")
        self.__network_enabled_label = self._create_label("enabled")
        self.__network_domain_label = self._create_label("domain")

    def _create_client(self) -> None:
        self.__client = DockerClient.from_env()

    def _get_enabled_networks(self) -> list[Network]:
        """
        Get all the enabled networks from the docker API

        A network is enabled if it has the following labels:
        - The network enabled label set to true
        - The network domain label
        """
        if not self.__client:
            self._create_client()
        return self.__client.networks.list(
            filters={
                "label": [
                    f"{self.__network_enabled_label}=true",
                    self.__network_domain_label,
                ]
            },
        )

    def _is_container_enabled(self, container: Container) -> bool:
        return (
            self.__container_enabled_label not in container.labels
            or container.labels[self.__container_enabled_label] == "true"
        )

    def _get_enabled_containers_on_network(self, network: Network) -> list[Container]:
        return [
            container
            for container in network.containers
            if self._is_container_enabled(container)
        ]

    def _get_container_domain(self, container: Container) -> str:
        return container.labels.get(self.__container_domain_label, container.name)

    def _get_network_domain(self, network: Network) -> str:
        try:
            # Get the domain label from the network's attrs property
            return network.attrs["Labels"][self.__network_domain_label]
        except KeyError:
            raise MissingNetworkDomainLabel(
                f"Network {network.name} is missing the domain label"
            )

    def _get_container_ipv4_on_network(
        self,
        container: Container,
        network: Network,
    ) -> str:
        container.reload()
        return container.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"]

    def yield_local_domains(self) -> Generator[LocalDomain, None, None]:
        """Get all the local domains from the docker API from a generator"""

        for network in self._get_enabled_networks():

            # Obtain network info
            network.reload()
            network_domain = self._get_network_domain(network)
            logging.debug("Network %s has domain %s", network.name, network_domain)

            for container in self._get_enabled_containers_on_network(network):

                # Obtain container info
                container.reload()
                container_domain = self._get_container_domain(container)
                ipv4 = self._get_container_ipv4_on_network(container, network)

                # Build local domain
                logging.debug(
                    "Container %s (%s) on network %s has subdomain %s and ipv4 %s",
                    container.name,
                    container.id,
                    network.name,
                    container_domain,
                    ipv4,
                )

                yield LocalDomain(
                    network_domain=network_domain,
                    container_domain=container_domain,
                    container_ipv4=ipv4,
                )

    def get_local_domains(self) -> list[LocalDomain]:
        """Get all the local domains from the docker API"""
        return [d for d in self.yield_local_domains()]
