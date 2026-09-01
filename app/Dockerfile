# -------------------------
# Stage 1: Python build stage
# -------------------------
FROM python:3.11-slim AS pybuilder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


# -------------------------
# Stage 2: Tailwind build stage
# -------------------------
FROM node:20-alpine AS nodebuilder
WORKDIR /src

# deps (cache-friendly)
COPY package.json package-lock.json ./
COPY tailwind.config.js ./
RUN npm ci

# Tailwind must see templates + input.css
COPY home ./home
COPY static ./static

RUN npm run build:css


# -------------------------
# Stage 3: Production runtime
# -------------------------
FROM python:3.11-slim

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

COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# app code
COPY --chown=appuser:appuser . .

# overwrite output.css with freshly built Tailwind
COPY --from=nodebuilder /src/static/css/output.css /app/static/css/output.css

USER appuser
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
