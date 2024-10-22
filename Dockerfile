FROM python:3.12-slim

# Install dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt
RUN rm /tmp/requirements.txt

# Install app
COPY src /src
WORKDIR /src

# Volumes
VOLUME /var/run/docker.sock
VOLUME /zones

ENV SLEEP_ON_SUCCESS=60
ENV SLEEP_ON_ERROR=5
ENV DNS_ZONE_FILES_DIR=/zones
ENV DNS_TTL=3600

CMD ["python", "main.py"]