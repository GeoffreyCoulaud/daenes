# Daenes

A simple solution for local DNS from docker labels.  
Watches docker containers for specific labels and sets entries for local DNS server accordingly, like traefik does for proxying.

## Installation

The only supported installation method is using docker.
See the [example docker compose](#example-docker-compose) section for more information.

## Configuration

### Docker labels for networks

<table>
  <thead>
    <tr>
      <th>Label</th>
      <th>Default</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>daenes.domain</code></td>
      <td>None, required</td>
      <td>
        The domain of the zone this network publishes, for instance
        <code>services.internal</code>.<br>
        A network without this label is left alone entirely.<br>
        It has to be a domain of at least two labels, made of letters, digits
        and hyphens. Two networks may name the same domain, in which case their
        containers land in the same zone.
      </td>
    </tr>
  </tbody>
</table>

### Docker labels for containers

<table>
  <thead>
    <tr>
      <th>Label</th>
      <th>Default</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>daenes.domain</code></td>
      <td>The container's name</td>
      <td>The subdomain to assign to this container inside its network's zone</td>
    </tr>
    <tr>
      <td><code>daenes.enabled</code></td>
      <td><code>true</code></td>
      <td>
        Whether to include the container.<br/>
        Some precisions : 
        <ul>
          <li>Containers are included if on a published network</li>
          <li>Containers are included by default, even with no <code>daenes.*</code> label</li>
          <li>Containers can be excluded explicitly by using this label</li>
        </ul>
      </td>
    </tr>
  </tbody>
</table>

### Environment variables

<table>
  <thead>
    <tr>
      <th>Name</th>
      <th>Default</th>
      <th>Optional</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>DNS_IP</code></td>
      <td></td>
      <td>Mandatory</td>
      <td>The IP address of the local DNS server to write inside of the zone files</td>
    </tr>
    <tr>
      <td><code>LOG_LEVEL</code></td>
      <td><code>INFO</code></td>
      <td>Optional</td>
      <td>
        Logs verbosity, available values are
        <code>DEBUG</code>,
        <code>INFO</code>,
        <code>WARNING</code>,
        <code>ERROR</code> and
        <code>CRITICAL</code>
      </td>
    </tr>
    <tr>
      <td><code>SUCCESS_INTERVAL</code></td>
      <td><code>60</code></td>
      <td>Optional</td>
      <td>Sleep interval between refreshes, in seconds</td>
    </tr>
    <tr>
      <td><code>RETRY_INTERVAL</code></td>
      <td><code>10</code></td>
      <td>Optional</td>
      <td>Sleep interval before trying again after a failure, in seconds</td>
    </tr>
    <tr>
      <td><code>DNS_TTL</code></td>
      <td><code>60</code></td>
      <td>Optional</td>
      <td>Time to live for DNS entries, in seconds. Zero tells resolvers not to cache them</td>
    </tr>
    <tr>
      <td><code>ZONES_DIR</code></td>
      <td><code>/zones</code></td>
      <td>Optional</td>
      <td>Directory the zone files are written into</td>
    </tr>
  </tbody>
</table>

### Volumes

The docker socket has to be mounted at `/var/run/docker.sock`: it is how daenes discovers networks and containers.

The zone files are written into `/zones`.  
Mounting a directory or docker volume there is the recommended way to access the zone files.

### Example docker compose

```yml
networks:

  # This network is watched, because it names the domain it publishes.
  services:
    labels:
      - daenes.domain=services.internal

  # This one too, under another domain.
  admin-services:
    labels:
      - daenes.domain=admin.internal

  # This network is not watched: it names no domain.
  some-internal-network:

services:

  daenes:
    image: ghcr.io/geoffreycoulaud/daenes:latest
    volumes:
      # The docker socket is needed to discover networks and containers
      - /var/run/docker.sock:/var/run/docker.sock
      # Directory where the zone files will be written
      - ./zones:/zones
    environment:
      # Change this IP at your discretion
      - DNS_IP=0.0.0.0

  # This container answers at www.services.internal and at www.admin.internal,
  # each with its address on the network in question.
  httpd:
    container_name: www
    image: httpd:latest
    ports:
      - "80:80"
    networks:
      # The name comes from the container, the domain from the network.
      services:
      # Same thing here, to show that a container may have several domains,
      # each pointing at its own address on the network it belongs to.
      admin-services:
```

A ready to run version of this example lives in [`examples/readme`](examples/readme).

## How domains are selected for containers

On a given docker network, daenes assigns one or more names to a container following these rules.

Its name:
- If the `daenes.domain` label is set on the container, it is used
- Otherwise the container's name is used, which is not the same as the compose service name

Its aliases, each published as a CNAME pointing at the name above:
- The compose service name, which docker makes an alias on every network
- Whatever aliases the container has on the network

The name and its aliases are then attached to the network's domain.

Names are lowercased, since DNS makes no difference between two spellings of one name. A name that could not be served is left out, with a line in the logs saying which and why:

- A name is made of letters, digits and hyphens, without a hyphen at either end (RFC 1123). Underscores are out, and docker puts one in the name it gives a compose network.
- A label may be 63 characters long, and a whole name 253 (RFC 1035).
- `ns` belongs to the zone's own nameserver, the one its NS record points at.

A container answers over whichever families its network carries: A on an IPv4 network, A and AAAA on a dual stack one, AAAA alone on a network created with `--ipv4=false`.

Two containers may share a name, in which case it answers with both addresses: which of them a client can reach is not for daenes to guess. A name that is both an address and an alias, or an alias pointing at two containers, is left out entirely instead: no answer could be defended, and RFC 2181 forbids the first outright.

A published network with nothing left on it still gets a zone, holding its nameserver alone, so the names that used to be there stop resolving. A zone is only rewritten when something in it changed, so its serial stays put as long as the deployment does.

## Upgrading from 0.2 to 1.0

- **A network is now published by naming its domain.** `daenes.enabled=true` on a network no longer publishes anything: replace it with `daenes.domain=<the domain you want>`. A network left with the old label is reported in the logs. The domain used to be guessed from the network's name, which docker prefixes with the compose project name and an underscore, and no DNS server would load the zone that came out of it.
- **`INTERVAL` is now `SUCCESS_INTERVAL`.**
- **The image no longer sets `LOG_LEVEL` to `DEBUG`.** It defaults to `INFO`, and can be set back.
- Zone files written under the old naming are left where they are. Delete the ones you no longer publish.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
