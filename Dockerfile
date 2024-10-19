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

CMD ["python", "main.py"]