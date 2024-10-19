from docker.client import DockerClient
from docker.models.containers import Container
from docker.models.networks import Network

from constants import PROJECT, RFQDN
from local_domain import LocalDomain


class DockerLabelObserver:

    __container_domain_label: str
    __container_enabled_label: str
    __network_enabled_label: str

    __client: DockerClient = None

    def _create_label(self, label: str) -> str:
        """Create a docker label prefixed by the project name and the domain name"""
        return f"{RFQDN}.{PROJECT}.{label}"

    def __init__(self) -> None:
        self.__container_domain_label = self._create_label("domain")
        self.__container_enabled_label = self._create_label("enabled")
        self.__network_enabled_label = self._create_label("enabled")

    def _create_client(self) -> None:
        self.__client = DockerClient.from_env()

    def _get_enabled_networks(self) -> list[Network]:
        if not self.__client:
            self._create_client()
        return self.__client.networks.list(
            filters={"label": [f"{self.__network_enabled_label}=true"]},
            greedy=True,
        )

    def _is_container_enabled(self, container: Container) -> bool:
        # By default, a container on an enabled network is enabled
        # It may be disabled by setting the label to false
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
        # Get the domain from the container label if present,
        # else use the container name
        return container.labels.get(self.__container_domain_label, container.name)

    def _get_container_ipv4_on_network(
        self,
        container: Container,
        network: Network,
    ) -> str:
        container.reload()
        return container.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"]

    def get_local_domains(self) -> list[LocalDomain]:
        """Get all the local domains from the docker API"""
        return [
            LocalDomain(
                container_id=container.id,
                domain=self._get_container_domain(container),
                ipv4=self._get_container_ipv4_on_network(container, network),
            )
            for network in self._get_enabled_networks()
            for container in self._get_enabled_containers_on_network(network)
        ]
