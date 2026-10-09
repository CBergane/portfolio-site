# -------------------------
# Stage 1: Python build stage
# -------------------------
FROM python:3.11.16-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b AS pybuilder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv --without-pip /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN /usr/local/bin/python -m pip --python /opt/venv install --require-hashes --only-binary=:all: -r requirements.txt \
    && /usr/local/bin/python -m pip --python /opt/venv check


# -------------------------
# Stage 2: Tailwind build stage
# -------------------------
FROM node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 AS nodebuilder
WORKDIR /src

# deps (cache-friendly)
COPY package.json package-lock.json ./
COPY tailwind.config.js ./
RUN npm ci --ignore-scripts

# Tailwind must see templates + input.css
COPY home ./home
COPY static ./static

RUN npm run build:css


# -------------------------
# Stage 3: Production runtime
# -------------------------
FROM python:3.11.16-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser && \
    mkdir -p /app /app/staticfiles /app/media && \
    chown -R appuser:appuser /app

COPY --from=pybuilder /opt/venv /opt/venv

WORKDIR /app

# Copy application code, then normalize executable scripts for Windows checkouts.
COPY --chown=appuser:appuser . .
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Copy compiled Tailwind CSS with correct ownership and permissions
COPY --chown=appuser:appuser --chmod=644 --from=nodebuilder /src/static/css/output.css /app/static/css/output.css

USER appuser
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
