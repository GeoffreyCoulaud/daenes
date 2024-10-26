import logging

from docker.client import DockerClient  # pylint: disable=import-error
from docker.models.containers import Container  # pylint: disable=import-error
from docker.models.networks import Network  # pylint: disable=import-error

from daenes.models.local_domain import LocalDomain


class MissingNetworkDomain(Exception):
    """Exception raised when a network has no domain set"""


class MissingContainerDomain(Exception):
    """Exception raised when a container has no domain set"""


class DockerService:

    __container_enabled_label: str
    __container_domain_label: str
    __network_enabled_label: str
    __network_domain_label: str

    __client: DockerClient = None

    def _create_label(self, label: str) -> str:
        """Create a docker label prefixed by the project name and the domain name"""
        return f"daenes.{label}"

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

        networks_by_id = {}

        # Get all the networks with the enabled label
        for network in self.__client.networks.list(
            filters={"label": f"{self.__network_enabled_label}=true"}
        ):
            logging.debug("Found enabled network %s (%s)", network.name, network.id)
            networks_by_id[network.id] = network

        # Get all the networks with the domain label
        # If a network has both labels, it will be added to the list only once
        # The renamed value takes precedence
        for network in self.__client.networks.list(
            filters={"label": self.__network_domain_label}
        ):
            msg = (
                "Found labelled network %s (%s)"
                if network.id not in networks_by_id
                else "Found labelled network %s (%s) (was found in enabled networks)"
            )
            networks_by_id[network.id] = network
            logging.debug(msg, network.name, network.id)

        return list(networks_by_id.values())

    def _is_container_enabled(self, container: Container) -> bool:
        return (
            self.__container_enabled_label not in container.labels
            or container.labels.get(self.__container_enabled_label, "true") == "true"
        )

    def _get_enabled_containers_on_network(self, network: Network) -> list[Container]:
        return [
            container
            for container in network.containers
            if self._is_container_enabled(container)
        ]

    def _get_container_domain_from_label(self, container: Container) -> str | None:
        return container.labels.get(self.__container_domain_label)

    def _get_container_domain_from_name(self, container: Container) -> str | None:
        return container.name

    def _get_container_domain_from_hostname(self, container: Container) -> str | None:
        return container.hostname

    def _get_container_domain(self, container: Container) -> str:
        domain_getters = {
            "label": self._get_container_domain_from_label,
            "name": self._get_container_domain_from_name,
            "hostname": self._get_container_domain_from_hostname,
        }
        for key, domain_getter in domain_getters.items():
            domain = domain_getter(container=container)
            if domain is not None:
                logging.debug("Container has domain %s (%s)", domain, key)
                break
        else:
            raise MissingContainerDomain("Container has no valid domain")
        return domain

    def _get_network_domain_from_label(self, network: Network) -> str | None:
        labels = network.attrs.get("Labels", dict())
        return labels.get(self.__network_domain_label)

    def _get_network_domain_from_name(self, network: Network) -> str | None:
        return network.name

    def _get_network_domain(self, network: Network) -> str:
        domain_getters = {
            "label": self._get_network_domain_from_label,
            "name": self._get_network_domain_from_name,
        }
        for key, domain_getter in domain_getters.items():
            domain = domain_getter(network=network)
            if domain is not None:
                logging.debug("Network has domain %s (%s)", domain, key)
                break
        else:
            raise MissingNetworkDomain("Network has no valid domain")
        return domain if "." in domain else f"{domain}.local"

    def _get_container_ip_on_network(
        self,
        container: Container,
        network: Network,
    ) -> str:
        container.reload()
        return container.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"]

    def _get_container_aliases_on_network(
        self,
        container: Container,
        network: Network,
    ) -> list[str]:
        container.reload()
        try:
            # fmt: off
            return container.attrs["NetworkSettings"]["Networks"][network.name]["Aliases"]
            # fmt: on
        except KeyError:
            return []

    def get_local_domains(self) -> list[LocalDomain]:
        """Get all the local domains from the docker API from a generator"""

        local_domains = []

        for network in self._get_enabled_networks():

            # Obtain network info
            network.reload()
            network_domain = self._get_network_domain(network)
            logging.debug("Network %s has domain %s", network.name, network_domain)

            for container in self._get_enabled_containers_on_network(network):

                # Obtain container info
                container.reload()
                ip = self._get_container_ip_on_network(container, network)
                main_domain = self._get_container_domain(container)
                aliases = self._get_container_aliases_on_network(container, network)
                logging.debug("Container has main domain %s", main_domain)
                logging.debug("Container has aliases %s", aliases)

                # Deduplicate domains
                domains = set[str]()
                domains.add(main_domain)
                domains.update(aliases)

                for domain in domains:

                    # Build local domain
                    logging.debug("Container has subdomain %s and ipv4 %s", domain, ip)

                    local_domain = LocalDomain(
                        parent=network_domain,
                        domain=domain,
                        ip=ip,
                    )
                    local_domains.append(local_domain)

        return local_domains
