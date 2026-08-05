"""The facts daenes assumes about the docker API.

Every constant here is a claim about someone else's software: the keys docker
answers with, and what it puts in them. Each is pinned against a real daemon by
a contract test in `end_to_end/test_contracts_docker.py`, and scripted by the
unit tests exercising the branch keying off it.

Sharing them is what makes the link mechanical: a docker release changing its
answers fails the test naming the fact, rather than surfacing in the middle of
an end-to-end run. `daenes.main` keeps its own literals, so that no test ever
proves a constant against itself.
"""

# What a network answers about itself.
LABELS_KEY = "Labels"
CONTAINERS_KEY = "Containers"

# Where a container carries the networks it is on, keyed by network name.
NETWORK_SETTINGS_KEY = "NetworkSettings"
NETWORKS_KEY = "Networks"

# What one network's settings hold.
IPV4_ADDRESS_KEY = "IPAddress"
IPV6_ADDRESS_KEY = "GlobalIPv6Address"

# Every name docker answers for a container on that network, which is what it
# resolves there and nothing less. Introduced in API 1.44, and the reason
# daenes asks for a daemon that speaks it.
DNS_NAMES_KEY = "DNSNames"

# What docker puts in an address key it has no address for.
NO_ADDRESS = ""

# What an event says it is about, and what happened to it. Read by the contract
# tests alone: daenes has the daemon filter its stream, so nothing in
# `daenes.main` ever opens an event to look inside.
EVENT_TYPE_KEY = "Type"
EVENT_ACTION_KEY = "Action"
