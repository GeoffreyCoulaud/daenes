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

Tests and linters live in the default `dev` group, installed by `uv sync`:

```sh
uv run pytest
```

Branch coverage must stay at 100%; the test run fails otherwise.

## Run the zone validity tests

The unit tests prove daenes writes what it meant to write. Whether that is a file a DNS server accepts is another question, and only a DNS server can answer it, so these tests hand every kind of zone daenes can produce to BIND's own checker:

```sh
uv run pytest daenes/tests/zone_validity -o addopts=""
```

The `-o addopts=""` resets the coverage flags from `pyproject.toml`: they target the unit tests, and nothing here is about covering `daenes.main`.

They need `named-checkzone`, and skip themselves with a message when it is missing:

```sh
sudo pacman -S bind          # Arch
sudo apt install bind9-utils # Debian, Ubuntu
```

The checker runs with the rules BIND applies to a primary zone rather than its own laxer defaults, which is the difference between a zone that loads and one that only looks like it would. In CI they run on every pull request, in a job that fails outright when the checker is absent rather than skipping quietly.

## Try it against a real docker daemon

There are no end-to-end tests. What stands in for them is [`examples/manual`](examples/manual), a deployment covering every rule daenes follows: a network that publishes nothing, a container opting out, one renamed by a label, one on two networks, one whose name no host may bear, and aliases.

```sh
cd examples/manual
docker compose up --build
cat zones/*.zone
```

Then, to check what came out is loadable:

```sh
named-checkzone -k fail -n fail -i full services.internal zones/services.internal.zone
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

Inside `daenes/main`:

- `model.py` is what daenes talks about: containers, networks, records, zones. It imports nothing but the standard library.
- `ports.py` declares what the core needs from the outside world, as `Protocol`s: a clock, somewhere networks come from, somewhere zones go.
- `zone_synchronizer.py` is the whole decision: which names a zone answers, with what, and when the file is worth rewriting. It knows nothing of docker or of files.
- `dns_names.py` holds the name rules, one per RFC, so they can be read against the RFC they come from.
- `docker.py` and `zone_files.py` are the two adapters, the only modules that know what docker and a file system are.
- `application.py` is the loop, `config.py` the environment, `main.py` the wiring and the exit codes.

A new port means a new `Protocol` in `ports.py`, an implementation of it in its own module, and a fake in `daenes/tests/unit/conftest.py`. The core never imports an adapter.
