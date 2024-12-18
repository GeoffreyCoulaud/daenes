FROM python:3.12-slim

# Install dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt
RUN rm /tmp/requirements.txt

# Install app
COPY daenes /app/daenes
WORKDIR /app
ENV PYTHONPATH=/app

# Volumes
VOLUME /var/run/docker.sock
VOLUME /zones

ENV LOG_LEVEL=DEBUG
ENV INTERVAL=60
ENV DNS_TTL=60

CMD ["python", "-m", "daenes.main"]