FROM python:3.12.12-slim-bookworm
# Headless Chromium lets agents render and screenshot their page.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash ca-certificates chromium curl fonts-dejavu-core git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
