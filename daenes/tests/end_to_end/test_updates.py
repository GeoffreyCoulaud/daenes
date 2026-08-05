"""What daenes does about a deployment that will not hold still.

The serial is what a secondary server watches to know a zone changed, so when
it moves, and when it does not, is as much of the contract as the records are.
"""

import time

from .conftest import NAMESERVER_NAME, RESYNC_INTERVAL, TIMEOUT, poll_until

# Long enough for several passes to go by, so that a zone left alone is left
# alone on purpose rather than not looked at yet.
OBSERVED_PASSES = 3

# What a change is given to reach the zone file, against a resync interval put
# an hour out of the way: nothing but the docker events can bridge that.
PROMPTLY = 10
AN_HOUR = 3600


def test_a_container_that_appears_is_published(
    network, deployment, start_daenes, zone, unique
):
    """Whether it was told or found out is settled below; here it is published."""
    web, late = unique("web"), unique("late")
    deployment.add_container(network, name=web)
    start_daenes()
    zone.wait_for_names({NAMESERVER_NAME, web})

    deployment.add_container(network, name=late)

    assert zone.wait_for_names({NAMESERVER_NAME, web, late})


def test_a_container_that_appears_is_published_without_waiting_for_a_pass(
    network, deployment, start_daenes, zone, unique
):
    """The docker daemon tells daenes, which is what this proves: the next pass
    daenes would make of its own accord is an hour out."""
    web, late = unique("web"), unique("late")
    deployment.add_container(network, name=web)
    start_daenes(RESYNC_INTERVAL_SECONDS=AN_HOUR)
    zone.wait_for_names({NAMESERVER_NAME, web})

    deployment.add_container(network, name=late)

    assert zone.wait_for_names({NAMESERVER_NAME, web, late}, timeout=PROMPTLY)


def test_a_container_that_goes_away_stops_resolving_without_waiting_for_a_pass(
    network, deployment, start_daenes, zone, unique
):
    """The same the other way round, and the one that matters more: a name
    outliving its container is worse than a name that took a while to appear."""
    web, going = unique("web"), unique("going")
    deployment.add_container(network, name=web)
    container = deployment.add_container(network, name=going)
    start_daenes(RESYNC_INTERVAL_SECONDS=AN_HOUR)
    zone.wait_for_names({NAMESERVER_NAME, web, going})

    deployment.remove(container)

    assert zone.wait_for_names({NAMESERVER_NAME, web}, timeout=PROMPTLY)


def test_a_container_that_goes_away_stops_resolving(
    network, deployment, start_daenes, zone, unique
):
    """A name outliving its container is worse than no name at all."""
    web, going = unique("web"), unique("going")
    deployment.add_container(network, name=web)
    container = deployment.add_container(network, name=going)
    start_daenes()
    zone.wait_for_names({NAMESERVER_NAME, web, going})

    deployment.remove(container)

    assert zone.wait_for_names({NAMESERVER_NAME, web})


def test_a_zone_nothing_changed_in_keeps_its_serial(
    network, deployment, start_daenes, zone, unique
):
    """Every rewrite is a transfer to every secondary server watching."""
    deployment.add_container(network, name=unique("web"))
    start_daenes()
    zone.wait()
    serial = zone.serial()

    time.sleep(RESYNC_INTERVAL * OBSERVED_PASSES)

    assert zone.serial() == serial


def test_a_zone_that_changed_gets_the_next_serial(
    network, deployment, start_daenes, zone, unique
):
    """Which is what tells a secondary server it has something to fetch."""
    web, late = unique("web"), unique("late")
    deployment.add_container(network, name=web)
    start_daenes()
    zone.wait_for_names({NAMESERVER_NAME, web})
    serial = zone.serial()

    deployment.add_container(network, name=late)

    zone.wait_for_names({NAMESERVER_NAME, web, late})
    assert zone.serial() == serial + 1


def test_a_restarted_daenes_carries_on_from_the_serial_on_disk(
    network, deployment, start_daenes, zone, unique
):
    """Remembering it would send every secondary server back in time on a redeploy.

    A restart rewrites the zone whether or not anything changed, since daenes
    has no way of knowing what happened while it was down.
    """
    deployment.add_container(network, name=unique("web"))
    daenes = start_daenes()
    zone.wait()
    serial = zone.serial()
    daenes.stop()

    start_daenes()

    poll_until(lambda: zone.serial() != serial, timeout=TIMEOUT)
    assert zone.serial() == serial + 1
