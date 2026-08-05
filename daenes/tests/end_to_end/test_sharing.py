"""What daenes does about the two things a deployment shares by accident.

Both make what a client gets depend on which container or network it happened
to reach, so both are refused until the environment says otherwise. Refusing
is proved the same way each time: a published network beside the shared one is
the clock, since daenes reads them all in one pass.
"""

from ..external_contracts import IPV4_ADDRESS_KEY
from .conftest import NAMESERVER_NAME, get_address, wait_for_log


def test_two_containers_sharing_a_name_are_both_left_out(
    network, deployment, start_daenes, zone, unique
):
    """One container's name is another's alias, which compose makes easy to do."""
    web, api, legacy = unique("web"), unique("api"), unique("legacy")
    deployment.add_container(network, name=api)
    deployment.add_container(network, name=legacy, aliases=(api,))
    deployment.add_container(network, name=web)

    daenes = start_daenes()

    assert zone.wait_for_names({NAMESERVER_NAME, web, legacy})
    wait_for_log(daenes, api, "ALLOW_MULTIPLE_ADDRESSES_PER_NAME")


def test_two_containers_sharing_a_name_answer_with_both_addresses_when_allowed(
    network, deployment, start_daenes, zone, unique
):
    """Round robin between interchangeable containers, once asked for."""
    api, legacy = unique("api"), unique("legacy")
    first = deployment.add_container(network, name=api)
    second = deployment.add_container(network, name=legacy, aliases=(api,))

    start_daenes(ALLOW_MULTIPLE_ADDRESSES_PER_NAME="true")

    records = zone.wait_for_names({NAMESERVER_NAME, api, legacy})
    assert records[api] == {
        get_address(first, network, IPV4_ADDRESS_KEY),
        get_address(second, network, IPV4_ADDRESS_KEY),
    }


def test_two_networks_sharing_a_zone_are_both_left_out(
    deployment, start_daenes, zone_for, origin, unique
):
    """Merging them would change what every name in the zone answers, not one."""
    witness_origin = f"{unique('witness')}.internal"
    witness = deployment.add_network(witness_origin)
    deployment.add_container(witness, name=unique("witness-web"))
    deployment.add_container(deployment.add_network(origin), name=unique("front"))
    deployment.add_container(deployment.add_network(origin), name=unique("back"))

    daenes = start_daenes()

    zone_for(witness_origin).wait()
    assert zone_for(origin).read() is None
    wait_for_log(daenes, origin, "ALLOW_MULTIPLE_NETWORKS_PER_ZONE")


def test_two_networks_sharing_a_zone_are_merged_when_allowed(
    deployment, start_daenes, zone, origin, unique
):
    """Both networks' containers in one zone, whichever one a client is on."""
    front, back = unique("front"), unique("back")
    deployment.add_container(deployment.add_network(origin), name=front)
    deployment.add_container(deployment.add_network(origin), name=back)

    start_daenes(ALLOW_MULTIPLE_NETWORKS_PER_ZONE="true")

    assert zone.wait_for_names({NAMESERVER_NAME, front, back})
