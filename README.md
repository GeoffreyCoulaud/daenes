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
      <td>The network's name</td>
      <td>
        The base local domain for containers of this network<br>
        If the name doesn't contain a <code>.</code>, a <code>.internal</code> suffix will be added.
      </td>
    </tr>
    <tr>
      <td><code>daenes.enabled</code></td>
      <td><code>false</code></td>
      <td>
        Whether daenes will look at containers for this network.<br/>
        Disabled by default, unless <code>daenes.domain</code> is set.
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
      <td>The base subdomain to assign to this container</td>
    </tr>
    <tr>
      <td><code>daenes.enabled</code></td>
      <td><code>true</code></td>
      <td>
        Whether to include the container.<br/>
        Some precisions : 
        <ul>
          <li>Containers are included if on an included network</li>
          <li>Containers are included by default, even with no <code>daenes.*</code> label</li>
          <li>Containers can be excluded explicitly from using this label</li>
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
      <td><code>LOG_LEVEL</code></td>
      <td><code>DEBUG</code></td>
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
      <td><code>INTERVAL</code></td>
      <td><code>60</code></td>
      <td>Optional</td>
      <td>Sleep interval between refreshes, in seconds</td>
    </tr>
    <tr>
      <td><code>DNS_TTL</code></td>
      <td><code>60</code></td>
      <td>Optional</td>
      <td>Time to live for DNS entries, in seconds</td>
    </tr>
    <tr>
      <td><code>DNS_IP</code></td>
      <td></td>
      <td>Mandatory</td>
      <td>The IP address of the local DNS server to write inside of the zone files</td>
    </tr>
  </tbody>
</table>

### Volumes

The zone files are written into `/zones`.  
Mounting a directory or docker volume there is the recommended way to access the zone files.

### Example docker compose

```yml
networks:

  # This network is watched because it matches **at least** one of the conditions
  # - It has daenes.enabled=true
  # - It has a daenes domain explicitly set 
  services:
    labels:
      - daenes.enabled=true
      - daenes.domain=services.internal
  
  # This network is also watched
  admin-services:
    labels:
      - daenes.enabled=true

  # This network is not watched
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

  # This container will generate a zone entry at web.services.internal
  # and web.admin-services.internal
  httpd:
    container_name: www
    image: httpd:latest
    ports:
      - "80:80"
    volumes:
      - ./sample-website:/usr/local/apache2/htdocs
    networks:
      # The domain name is generated because the container is on the
      # services network, which is watched by daenes.
      - services
      # Same thing here, to show that a container may have multiple domains
      # all pointing at its correct IP on the appropriate network
      - admin-services
```

## How domains are selected for containers

On a given docker network, daenes will assign one or more domain names following these rules

Base subdomain:
- If the `daenes.domain` label is set, it is used as the subdomain
- Else the container name is used (different from the service name)

Secondary subdomains:
- If the container has aliases on the network, they are used for secondary subdomains

Finally, the subdomains are attached to the network's domain.
