# syntax=docker/dockerfile:1
# Serveur MCP en transport Streamable HTTP, pour le connecteur distant.
# Il n'appelle que l'API publique : aucun acces a la base.
FROM python:3.14-slim-trixie AS base

# Certificats d'autorite supplementaires. Le dossier est vide en temps normal : il
# n'existe que pour les environnements de construction derriere un proxy qui termine
# le TLS (voir infra/docker/ca/README.md). On concatene plutot que d'installer
# `ca-certificates` avec apt : l'image le contient deja, et cela evite toute
# dependance reseau supplementaire a la construction.
COPY infra/docker/ca /tmp/ca-supplementaires
RUN set -eux; \
    cat /etc/ssl/certs/ca-certificates.crt /tmp/ca-supplementaires/*.crt \
        > /etc/ssl/certs/ca-carburant.crt 2>/dev/null \
    || cp /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-carburant.crt; \
    rm -rf /tmp/ca-supplementaires
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-carburant.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-carburant.crt

# uv depuis PyPI plutot que depuis ghcr.io/astral-sh/uv : une seule registry pour
# toute l'image, et aucune dependance a un second registre de conteneurs.
ARG UV_VERSION=0.13.9
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY etl/pyproject.toml etl/
COPY api/pyproject.toml api/
COPY mcp/pyproject.toml mcp/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --package prix-carburant-mcp

COPY mcp/ mcp/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package prix-carburant-mcp

ENV PATH="/app/.venv/bin:${PATH}"

RUN useradd --system --uid 10003 carburant
USER carburant

EXPOSE 8001
CMD ["prix-carburant-mcp", "--transport", "http"]
