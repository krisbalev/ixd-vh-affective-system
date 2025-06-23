# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# ---- system deps ---------------------------------------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        gcc g++ \
 && rm -rf /var/lib/apt/lists/*

# ---- python deps ---------------------------------------------------------
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ---- application  --------------------------------------------------------
COPY . .

# Expose nothing: this service talks via Kafka/HTTP only.
CMD ["python", "-m", "main"]