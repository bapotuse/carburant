# syntax=docker/dockerfile:1
# ETL : collecte, nettoyage et historisation des prix.
FROM python:3.14-slim-trixie AS base

# Certificats d'autorite supplementaires (vide en temps normal : voir ca/README.md).
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

# La planification (supercronic) arrive au Jalon 1, avec la premiere collecte reelle :
# au Jalon 0 le conteneur n'a rien a planifier. Voir docs/avancement.md.

# uv depuis PyPI plutot que depuis ghcr.io/astral-sh/uv : une seule registry pour
# toute l'image, et aucune dependance a un second registre de conteneurs.
ARG UV_VERSION=0.13.9
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Couche de dependances : ne change que si les manifestes changent.
COPY pyproject.toml uv.lock ./
COPY etl/pyproject.toml etl/
COPY api/pyproject.toml api/
COPY mcp/pyproject.toml mcp/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --package carburant-etl

COPY etl/ etl/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package carburant-etl

ENV PATH="/app/.venv/bin:${PATH}"

# Utilisateur non-root, proprietaire du repertoire des fichiers bruts.
RUN set -eux; \
    useradd --system --create-home --uid 10001 carburant; \
    mkdir -p /app/data/raw; \
    chown -R carburant:carburant /app/data
USER carburant

# Pas de HEALTHCHECK : ce conteneur n'est pas un service qui repond, c'est un
# planificateur. Sa sante se lit dans meta.execution_etl et dans le dead man's switch
# (healthchecks.io), pas dans un ping.

CMD ["etl", "run"]
