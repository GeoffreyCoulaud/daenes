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
    zone = synchronize_one(make_published_network(make_domain("web")))

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
        make_published_network(make_domain("web"), origin="services.internal"),
        make_published_network(make_domain("db"), origin="admin.internal"),
    )

    assert [zone.origin for zone in saved] == ["admin.internal", "services.internal"]


def test_two_networks_naming_one_origin_are_refused_by_default(caplog):
    """Merging changes what every name answers, so it is asked for explicitly."""
    saved = synchronize(
        make_published_network(make_domain("web"), name="front"),
        make_published_network(make_domain("db"), name="back"),
    )

    assert saved == []
    assert "back, front" in caplog.text


def test_two_networks_naming_one_origin_land_in_one_zone():
    """Merging them is a deliberate use, and has to be asked for."""
    zone = synchronize_one(
        make_published_network(make_domain("web", addresses=("172.20.0.2",))),
        make_published_network(make_domain("db", addresses=("172.21.0.2",))),
        allowances=MERGED_NETWORKS,
    )

    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)
    assert addresses_of(zone, "db") == (ip_address("172.21.0.2"),)


def test_an_origin_is_matched_without_regard_to_case():
    """RFC 4343: two spellings of one domain are one domain."""
    zone = synchronize_one(
        make_published_network(make_domain("web"), origin="Services.Internal"),
        make_published_network(make_domain("db"), origin="services.internal"),
        allowances=MERGED_NETWORKS,
    )

    assert zone.origin == "services.internal"
    assert set(names_of(zone)) == {NAMESERVER_NAME, "web", "db"}


def test_a_container_reachable_at_several_addresses_answers_with_all_of_them():
    """Once the deployment asks for it, the client picks and daenes says nothing."""
    zone = synchronize_one(
        make_published_network(make_domain("web", addresses=("172.20.0.2",))),
        make_published_network(make_domain("web", addresses=("172.21.0.9",))),
        allowances=SHARED_NAMES,
    )

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("172.21.0.9"),
    )


def test_addresses_are_ordered_by_family_then_value():
    """The two families do not compare, and the output has to be stable."""
    domain = make_domain("web", addresses=("fd00::2", "172.20.0.9", "172.20.0.2"))

    zone = synchronize_one(make_published_network(domain), allowances=SHARED_NAMES)

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("172.20.0.9"),
        ip_address("fd00::2"),
    )


def test_every_name_of_a_container_answers_with_its_addresses():
    """None of them is more canonical than the others, so none points at another.

    Docker's own resolver answers them all the same way, with no CNAME.
    """
    domain = make_domain("web", "www", "front")

    zone = synchronize_one(make_published_network(domain))

    assert addresses_of(zone, "www") == (ip_address("172.20.0.2"),)
    assert addresses_of(zone, "front") == (ip_address("172.20.0.2"),)


def test_a_second_name_of_a_container_on_two_networks_answers_with_both():
    """A container on two merged networks answers to its names on each."""
    zone = synchronize_one(
        make_published_network(
            make_domain("web", "www", addresses=("172.20.0.2",))
        ),
        make_published_network(
            make_domain("web", "www", addresses=("172.21.0.2",))
        ),
        allowances=SHARED_NAMES,
    )

    assert addresses_of(zone, "www") == (
        ip_address("172.20.0.2"),
        ip_address("172.21.0.2"),
    )


def test_a_container_one_of_whose_names_is_unservable_keeps_the_others():
    """Each name stands on its own, so an unservable one takes nothing with it."""
    domain = make_domain("my_service", "api")

    zone = synchronize_one(make_published_network(domain))

    assert set(names_of(zone)) == {NAMESERVER_NAME, "api"}


def test_a_name_two_containers_answer_to_is_dropped(caplog):
    """A deployment arrives at this by accident more often than on purpose."""
    zone = synchronize_one(
        make_published_network(
            make_domain("www", addresses=("172.20.0.3",)),
            make_domain("web", "www", addresses=("172.20.0.2",)),
        )
    )

    assert addresses_of(zone, "www") is None
    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)
    assert "Ignoring the name 'www'" in caplog.text


def test_a_name_two_containers_claim_is_dropped(caplog):
    """Two networks sharing a domain may each hold a container of one name."""
    zone = synchronize_one(
        make_published_network(
            make_domain("web", addresses=("172.20.0.2",), container="one")
        ),
        make_published_network(
            make_domain("web", addresses=("172.21.0.2",), container="two")
        ),
        allowances=MERGED_NETWORKS,
    )

    assert addresses_of(zone, "web") is None
    assert "172.20.0.2, 172.21.0.2" in caplog.text
    assert "one, two" in caplog.text


def test_a_container_on_two_networks_of_one_zone_is_dropped_too(caplog):
    """One container or two, a client still reaches whichever it is handed."""
    zone = synchronize_one(
        make_published_network(make_domain("web", addresses=("172.20.0.2",))),
        make_published_network(make_domain("web", addresses=("172.21.0.2",))),
        allowances=MERGED_NETWORKS,
    )

    assert addresses_of(zone, "web") is None
    assert "Ignoring the name 'web'" in caplog.text


def test_a_name_answering_over_both_families_is_left_alone(caplog):
    """Dual stack is one host over two protocols, not a choice between two."""
    domain = make_domain("web", addresses=("172.20.0.2", "fd00::2"))

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
            make_domain("web", addresses=("172.20.0.2",), container="one")
        ),
        make_published_network(
            make_domain("web", addresses=("172.21.0.2",), container="two")
        ),
        allowances=SHARED_NAMES,
    )

    assert addresses_of(zone, "web") == (
        ip_address("172.20.0.2"),
        ip_address("172.21.0.2"),
    )
    assert not caplog.text


def test_the_nameserver_name_belongs_to_the_zone_alone(caplog):
    """Handing it to a container would leave the zone's NS record lying."""
    domain = make_domain("web", NAMESERVER_NAME)

    zone = synchronize_one(make_published_network(domain))

    # Whatever else the container is known by, the nameserver's name answers
    # with the address the configuration gave, and with nothing else.
    assert addresses_of(zone, NAMESERVER_NAME) == (NAMESERVER_ADDRESS,)
    assert set(names_of(zone)) == {NAMESERVER_NAME, "web"}
    assert "nameserver" in caplog.text


@pytest.mark.parametrize(
    "name",
    ["my_service", "-web", ""],
    ids=["underscore", "leading_hyphen", "empty"],
)
def test_a_name_that_no_host_may_bear_is_ignored(name):
    zone = synchronize_one(
        make_published_network(make_domain(name), make_domain("web"))
    )

    assert set(names_of(zone)) == {NAMESERVER_NAME, "web"}


def test_a_name_already_ending_in_the_zones_domain_is_not_repeated():
    """Writing it as it stands would answer for web.services.internal.services.internal.

    Which is what someone naming their container after the name they want to
    resolve would get, and it is the natural thing to do.
    """
    domain = make_domain(f"web.{ORIGIN}")

    zone = synchronize_one(make_published_network(domain))

    assert addresses_of(zone, "web") == (ip_address("172.20.0.2"),)


def test_a_container_named_after_the_zone_itself_answers_for_the_domain():
    """A deployment saying this container is what the domain is for."""
    domain = make_domain(ORIGIN)

    zone = synchronize_one(make_published_network(domain))

    assert addresses_of(zone, "") == (ip_address("172.20.0.2"),)


def test_a_name_belonging_to_another_domain_is_published_under_this_one():
    """Daenes only serves under its own domain, and says what it publishes.

    Nothing tells this apart from a deployment organising itself in
    subdomains, which is a use of its own.
    """
    domain = make_domain("mail.example.com")

    zone = synchronize_one(make_published_network(domain))

    assert addresses_of(zone, "mail.example.com") == (ip_address("172.20.0.2"),)


def test_a_name_too_long_for_its_zone_is_ignored():
    """The limit is on the whole name, so a long zone leaves less room."""
    origin = ".".join(["a" * 60] * 4)
    room_left = MAX_NAME_LENGTH - len(origin) - len(".")

    zone = synchronize_one(
        make_published_network(
            make_domain("b" * room_left),
            make_domain("c" * (room_left + 1)),
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
        [make_published_network(make_domain("web"))]
    )

    synchronizer.synchronize()
    source.networks[0] = make_published_network(
        make_domain("web"), make_domain("db")
    )
    synchronizer.synchronize()

    assert [zone.serial for zone in store.saved] == [1, 2]
    assert set(names_of(store.saved[-1])) == {NAMESERVER_NAME, "web", "db"}
