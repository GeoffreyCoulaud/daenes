# Contributing

This project uses [uv](https://docs.astral.sh/uv/) for dependency management. Install it first.

## Run the app locally (without Docker)

Install dependencies (docker + the project, editable):

```sh
uv sync
```

Run daenes against your own docker daemon, writing zones where you can look at them (see the [README](README.md#environment-variables) for the rest of the environment):

```sh
mkdir -p zones
DNS_IP="0.0.0.0" \
ZONES_DIR="./zones" \
LOG_LEVEL="DEBUG" \
uv run daenes
```

Nothing is published until a network names a domain, so label one first:

```sh
docker network create --label daenes.domain=services.internal services
```

## Run the tests

Tests and linters live in the default `dev` group, installed by `uv sync`. There are four suites, each answering a question the others cannot:

| Suite | What it settles | What it needs |
|---|---|---|
| `unit` | that the core decides what it is supposed to decide | nothing |
| `end_to_end -m contract` | that docker really answers what the fakes pretend it does | a docker daemon |
| `end_to_end -m "not contract"` | that the image, over a real daemon, writes the zones a deployment calls for | a daemon, and it builds the image |
| `zone_validity` | that a DNS server would load what daenes writes | `named-checkzone` |

Only the first runs by default, since it is the only one that needs nothing:

```sh
uv run pytest
```

Branch coverage must stay at 100%; the run fails otherwise.

Every other suite is asked for by path, with `-o addopts=""` to drop the coverage flags: they target the unit tests, and nothing else is about covering `daenes.main`.

### Contract tests

Every branch in `daenes/main/docker.py` keys off something docker is assumed to do, and so does every action in the event filter of `daenes/main/docker_events.py`. The unit tests can only restate those assumptions, since their fakes are where the assumptions live. These check them against a real daemon, one fact per test:

```sh
uv run pytest daenes/tests/end_to_end -o addopts="" -m contract
```

The facts themselves are constants in [`daenes/tests/external_contracts.py`](daenes/tests/external_contracts.py), shared with the unit fakes. That sharing is what makes the link mechanical: a docker release changing its answers fails the test naming the fact, instead of surfacing in the middle of an end-to-end run.

### End-to-end tests

The real image, built from the Dockerfile, reading a real daemon and writing real zone files, asserted from the outside:

```sh
uv run pytest daenes/tests/end_to_end -o addopts="" -m "not contract" -n 4
```

Daenes reads the whole daemon rather than one network of it, so nothing here is isolated the way a client and a server would be. Each test gets a zone of its own instead, and only ever looks at that zone. That is what lets them run in parallel, and on the daemon you already have things running on.

No secret is involved, so they run on every pull request, forks included.

### Zone validity tests

The unit tests prove daenes writes what it meant to write. Whether that is a file a DNS server accepts is another question, and only a DNS server can answer it, so these hand every kind of zone daenes can produce to BIND's own checker:

```sh
uv run pytest daenes/tests/zone_validity -o addopts=""
```

They need `named-checkzone`, and skip themselves with a message when it is missing:

```sh
sudo pacman -S bind          # Arch
sudo apt install bind9-utils # Debian, Ubuntu
```

The checker runs with the rules BIND applies to a primary zone rather than its own laxer defaults, which is the difference between a zone that loads and one that only looks like it would. In CI they run in a job that fails outright when the checker is absent, rather than skipping quietly.

## Try it by hand

[`examples/manual`](examples/manual) is a deployment covering every rule daenes follows: a network that publishes nothing, a container opting out, one on two networks, one whose name no host may bear, one sharing a name with another, aliases, hostnames, a name that already carries the zone's domain, and one container named after the domain itself. The end-to-end suite covers the same ground; this is for watching it happen.

```sh
cd examples/manual
docker compose up --build
cat zones/*.zone
```

## Lint

```sh
uv run pylint daenes
uv run pyright daenes
docker run --rm -v "$(pwd):/repo" --workdir /repo rhysd/actionlint:1.7.12
```

Both linters cover the tests as well as the application.

## How the code is laid out

`daenes/main` holds the application, `daenes/tests` the tests, and neither the core nor the tests reach across that line the wrong way.

Inside `daenes/tests`:

- `unit/` is the only suite in `testpaths`, and the only one holding the coverage bar.
- `end_to_end/` holds both suites that need a daemon, told apart by the `contract` marker. Their fixtures are shared, and the image is only built for the tests that ask for it.
- `external_contracts.py` and `zone_checker.py` are what two suites share: the keys docker answers with, and the way a zone is handed to BIND.

Inside `daenes/main`:

- `model.py` is what daenes talks about: containers, networks, records, zones. It imports nothing but the standard library.
- `ports.py` declares what the core needs from the outside world, as `Protocol`s: a clock, something that says the deployment changed, somewhere networks come from, somewhere zones go.
- `zone_synchronizer.py` is the whole decision: which names a zone answers, with what, and when the file is worth rewriting. It knows nothing of docker or of files.
- `dns_names.py` holds the name rules, one per RFC, so they can be read against the RFC they come from.
- `docker.py`, `docker_events.py` and `zone_files.py` are the adapters, the only modules that know what docker and a file system are. The second reads the daemon's event stream, and turns everything it says into the one thing the core asks of it: that the deployment is worth reading again. It never looks inside an event, since the daemon is the one filtering them.
- `application.py` is the loop, `config.py` the environment, `main.py` the wiring and the exit codes.

A new port means a new `Protocol` in `ports.py`, an implementation of it in its own module, and a fake in `daenes/tests/unit/conftest.py`. The core never imports an adapter.

A new assumption about what docker answers means a constant in `external_contracts.py` and a contract test checking it, rather than a value written straight into a fake where nothing would ever question it.
