FROM python:3.12-slim

# Install dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt
RUN rm /tmp/requirements.txt

# Install app
COPY daenes /daenes
WORKDIR /daenes

# Volumes
VOLUME /var/run/docker.sock
VOLUME /zones

ENV INTERVAL=60
ENV DNS_TTL=60

CMD ["python", "main.py"]