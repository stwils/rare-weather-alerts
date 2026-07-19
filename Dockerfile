FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY config ./config
COPY data/thresholds.json ./data/thresholds.json

ENV RWA_ROOT=/app
# state lives on a mounted volume: -v ./state:/app/state
CMD ["rare-weather", "daemon"]
