"""Unit tests for daenes.main.zone_synchronizer."""

from ipaddress import ip_address

import pytest

from daenes.main.dns_names import MAX_NAME_LENGTH
from daenes.main.model import Allowances
from daenes.main.zone_synchronizer import (
    FIRST_SERIAL,
    NAMESERVER_NAME,
    SERIAL_MODULO,
    ZoneSynchronizer,
)

from .conftest import (
    NAMESERVER_ADDRESS,
    ORIGIN,
    TTL,
    FakeNetworkSource,
    FakeZoneStore,
    addresses_of,
    make_domain,
    make_published_network,
    names_of,
)


# What a deployment gets without asking for anything, and the two things it
# may ask for. Spelled out here so every test says which one it is about.
NOTHING_ALLOWED = Allowances()
MERGED_NETWORKS = Allowances(multiple_networks_per_zone=True)
SHARED_NAMES = Allowances(
    multiple_addresses_per_name=True,
    multiple_networks_per_zone=True,
)


def make_synchronizer(networks, store=None, allowances=NOTHING_ALLOWED):
    """A synchronizer over a deployment and a store the test can look into."""
    source = FakeNetworkSource(tuple(networks))
    store = FakeZoneStore() if store is None else store
    synchronizer = ZoneSynchronizer(
        source=source,
        store=store,
        nameserver_address=NAMESERVER_ADDRESS,
        ttl=TTL,
        allowances=allowances,
    )
    return synchronizer, source, store


def synchronize(*networks, store=None, allowances=NOTHING_ALLOWED):
    """Run one synchronization, and answer the zones it wrote."""
    synchronizer, _, store = make_synchronizer(networks, store, allowances)
    synchronizer.synchronize()
    return store.saved


def synchronize_one(*networks, store=None, allowances=NOTHING_ALLOWED):
    """Run one synchronization that is expected to write exactly one zone."""
    saved = synchronize(*networks, store=store, allowances=allowances)
    assert len(saved) == 1
    return saved[0]


def test_a_zone_carries_its_origin_its_ttl_and_its_nameserver():
    zone = synchronize_one(make_published_network(make_domain(name="web")))

    assert zone.origin == ORIGIN
    assert zone.ttl == TTL
    assert addresses_of(zone, NAMESERVER_NAME) == (NAMESERVER_ADDRESS,)
    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)


def test_a_network_everything_left_still_gets_a_zone():
    """Otherwise the names that used to be on it would go on resolving."""
    zone = synchronize_one(make_published_network())

    assert set(names_of(zone)) == {NAMESERVER_NAME}


def test_each_origin_becomes_its_own_zone():
    saved = synchronize(
        make_published_network(make_domain(name="web"), origin="services.internal"),
        make_published_network(make_domain(name="db"), origin="admin.internal"),
    )

    assert [zone.origin for zone in saved] == ["admin.internal", "services.internal"]


def test_two_networks_naming_one_origin_are_refused_by_default(caplog):
    """Merging changes what every name answers, so it is asked for explicitly."""
    saved = synchronize(
        make_published_network(make_domain(name="web"), name="front"),
        make_published_network(make_domain(name="db"), name="back"),
    )

    assert saved == []
    assert "back, front" in caplog.text


def test_two_networks_naming_one_origin_land_in_one_zone():
    """Merging them is a deliberate use, and has to be asked for."""
    zone = synchronize_one(
        make_published_network(make_domain(name="web", addresses=("172.20.0.2",))),
        make_published_network(make_domain(name="db", addresses=("172.21.0.2",))),
        allowances=MERGED_NETWORKS,
    )

    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)
    assert addresses_of(zone, "db") == (ip_address("172.21.0.2"),)


def test_an_origin_is_matched_without_regard_to_case():
    """RFC 4343: two spellings of one domain are one domain."""
    zone = synchronize_one(
        make_published_network(make_domain(name="web"), origin="Services.Internal"),
        make_published_network(make_domain(name="db"), origin="services.internal"),
        allowances=MERGED_NETWORKS,
    )

    assert zone.origin == "services.internal"
    assert set(names_of(zone)) == {NAMESERVER_NAME, "web", "db"}


def test_a_container_reachable_at_several_addresses_answers_with_all_of_them():
    """Once the deployment asks for it, the client picks and daenes says nothing."""
    zone = synchronize_one(
        make_published_network(make_domain(name="web", addresses=("172.20.0.2",))),
        make_published_network(make_domain(name="web", addresses=("172.21.0.9",))),
        allowances=SHARED_NAMES,
    )

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("172.21.0.9"),
    )


def test_addresses_are_ordered_by_family_then_value():
    """The two families do not compare, and the output has to be stable."""
    domain = make_domain(name="web", addresses=("fd00::2", "172.20.0.9", "172.20.0.2"))

    zone = synchronize_one(make_published_network(domain), allowances=SHARED_NAMES)

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("172.20.0.9"),
        ip_address("fd00::2"),
    )


def test_an_alias_answers_with_the_addresses_of_its_container():
    """Docker's own resolver answers an alias the same way, with no CNAME."""
    domain = make_domain(name="web", aliases=("www", "front"))

    zone = synchronize_one(make_published_network(domain))

    assert addresses_of(zone, "www") == (ip_address("172.20.0.2"),)
    assert addresses_of(zone, "front") == (ip_address("172.20.0.2"),)


def test_a_container_listed_among_its_own_aliases_is_one_name():
    """Docker lists a container's own name among its aliases."""
    domain = make_domain(name="web", aliases=("web", "www"))

    zone = synchronize_one(make_published_network(domain))

    assert set(names_of(zone)) == {NAMESERVER_NAME, "web", "www"}


def test_an_alias_of_a_container_on_two_networks_answers_with_both_addresses():
    """A container on two merged networks reports its aliases on each."""
    zone = synchronize_one(
        make_published_network(
            make_domain(name="web", addresses=("172.20.0.2",), aliases=("www",))
        ),
        make_published_network(
            make_domain(name="web", addresses=("172.21.0.2",), aliases=("www",))
        ),
        allowances=SHARED_NAMES,
    )

    assert addresses_of(zone, "www") == (
        ip_address("172.20.0.2"),
        ip_address("172.21.0.2"),
    )


def test_a_container_kept_out_of_dns_still_answers_through_its_aliases():
    """Each name stands on its own, so an unservable one takes nothing with it."""
    domain = make_domain(name="my_service", aliases=("api",))

    zone = synchronize_one(make_published_network(domain))

    assert set(names_of(zone)) == {NAMESERVER_NAME, "api"}


def test_a_name_shared_by_a_container_and_an_alias_is_dropped(caplog):
    """A deployment arrives at this by accident more often than on purpose."""
    zone = synchronize_one(
        make_published_network(
            make_domain(name="www", addresses=("172.20.0.3",)),
            make_domain(name="web", addresses=("172.20.0.2",), aliases=("www",)),
        )
    )

    assert addresses_of(zone, "www") is None
    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)
    assert "Ignoring the name 'www'" in caplog.text


def test_a_name_two_containers_claim_is_dropped(caplog):
    """Two networks sharing a domain may each hold a container of one name."""
    zone = synchronize_one(
        make_published_network(
            make_domain(name="web", addresses=("172.20.0.2",), container="one")
        ),
        make_published_network(
            make_domain(name="web", addresses=("172.21.0.2",), container="two")
        ),
        allowances=MERGED_NETWORKS,
    )

    assert addresses_of(zone, "web") is None
    assert "172.20.0.2, 172.21.0.2" in caplog.text
    assert "one, two" in caplog.text


def test_a_container_on_two_networks_of_one_zone_is_dropped_too(caplog):
    """One container or two, a client still reaches whichever it is handed."""
    zone = synchronize_one(
        make_published_network(make_domain(name="web", addresses=("172.20.0.2",))),
        make_published_network(make_domain(name="web", addresses=("172.21.0.2",))),
        allowances=MERGED_NETWORKS,
    )

    assert addresses_of(zone, "web") is None
    assert "Ignoring the name 'web'" in caplog.text


def test_a_name_answering_over_both_families_is_left_alone(caplog):
    """Dual stack is one host over two protocols, not a choice between two."""
    domain = make_domain(name="web", addresses=("172.20.0.2", "fd00::2"))

    zone = synchronize_one(make_published_network(domain))

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("fd00::2"),
    )
    assert "Ignoring" not in caplog.text


def test_several_addresses_may_be_asked_for(caplog):
    """The advanced use, which has to be turned on rather than fallen into."""
    zone = synchronize_one(
        make_published_network(
            make_domain(name="web", addresses=("172.20.0.2",), container="one")
        ),
        make_published_network(
            make_domain(name="web", addresses=("172.21.0.2",), container="two")
        ),
        allowances=SHARED_NAMES,
    )

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("172.21.0.2"),
    )
    assert not caplog.text


@pytest.mark.parametrize(
    "domain",
    [make_domain(name=NAMESERVER_NAME), make_domain(aliases=(NAMESERVER_NAME,))],
    ids=["as_a_container", "as_an_alias"],
)
def test_the_nameserver_name_belongs_to_the_zone_alone(domain):
    """Handing it to a container would leave the zone's NS record lying."""
    zone = synchronize_one(make_published_network(domain))

    # Whatever the container is called elsewhere, the nameserver's name
    # answers with the address the configuration gave, and with nothing else.
    assert addresses_of(zone, NAMESERVER_NAME) == (NAMESERVER_ADDRESS,)


@pytest.mark.parametrize(
    "name",
    ["my_service", "-web", ""],
    ids=["underscore", "leading_hyphen", "empty"],
)
def test_a_container_that_cannot_be_named_in_dns_is_ignored(name):
    zone = synchronize_one(
        make_published_network(make_domain(name=name), make_domain(name="web"))
    )

    assert set(names_of(zone)) == {NAMESERVER_NAME, "web"}


def test_an_alias_that_cannot_be_named_in_dns_is_ignored():
    domain = make_domain(name="web", aliases=("my_alias", "www"))

    zone = synchronize_one(make_published_network(domain))

    assert set(names_of(zone)) == {NAMESERVER_NAME, "web", "www"}


def test_a_name_too_long_for_its_zone_is_ignored():
    """The limit is on the whole name, so a long zone leaves less room."""
    origin = ".".join(["a" * 60] * 4)
    room_left = MAX_NAME_LENGTH - len(origin) - len(".")

    zone = synchronize_one(
        make_published_network(
            make_domain(name="b" * room_left),
            make_domain(name="c" * (room_left + 1)),
            origin=origin,
        )
    )

    assert set(names_of(zone)) == {NAMESERVER_NAME, "b" * room_left}


@pytest.mark.parametrize(
    "origin",
    ["compose_services.internal", "services"],
    ids=["not_a_domain", "single_label"],
)
def test_a_zone_nobody_could_serve_is_not_written(origin):
    """A compose network is named after its project, underscore included."""
    saved = synchronize(
        make_published_network(make_domain(), origin=origin),
        make_published_network(make_domain(), origin="services.internal"),
    )

    assert [zone.origin for zone in saved] == ["services.internal"]


def test_the_first_serial_of_a_zone_is_one():
    zone = synchronize_one(make_published_network(make_domain()))

    assert zone.serial == FIRST_SERIAL


def test_a_serial_carries_on_from_the_zone_already_on_disk():
    """Going back in time would leave every secondary server on the old zone."""
    store = FakeZoneStore({ORIGIN: 41})

    zone = synchronize_one(make_published_network(make_domain()), store=store)

    assert zone.serial == 42


def test_a_serial_wraps_around():
    """RFC 1982: the serial is unsigned 32 bit arithmetic."""
    store = FakeZoneStore({ORIGIN: SERIAL_MODULO - 1})

    zone = synchronize_one(make_published_network(make_domain()), store=store)

    assert zone.serial == 0


def test_an_unchanged_zone_is_left_alone():
    """Rewriting it would bump the serial, which every secondary takes for news."""
    synchronizer, _, store = make_synchronizer(
        [make_published_network(make_domain())]
    )

    synchronizer.synchronize()
    synchronizer.synchronize()

    assert len(store.saved) == 1


def test_a_changed_zone_is_written_again_with_a_new_serial():
    synchronizer, source, store = make_synchronizer(
        [make_published_network(make_domain(name="web"))]
    )

    synchronizer.synchronize()
    source.networks[0] = make_published_network(
        make_domain(name="web"), make_domain(name="db")
    )
    synchronizer.synchronize()

    assert [zone.serial for zone in store.saved] == [1, 2]
    assert set(names_of(store.saved[-1])) == {NAMESERVER_NAME, "web", "db"}
