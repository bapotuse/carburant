# syntax=docker/dockerfile:1
# API publique.
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
    uv sync --frozen --no-install-workspace --package carburant-api

COPY api/ api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package carburant-api

ENV PATH="/app/.venv/bin:${PATH}"

RUN useradd --system --uid 10002 carburant
USER carburant

EXPOSE 8000

# Le healthcheck interroge /v1/meta, pas /v1/sante, et la distinction compte.
#
#   /v1/meta  repond « ce conteneur sait servir » : l'application tourne et la base
#             repond. C'est une question a laquelle un redemarrage peut repondre.
#   /v1/sante repond « le service est en bon etat », donnees comprises : il renvoie
#             503 quand la derniere collecte reussie est trop vieille. C'est la
#             question que pose la supervision, et un redemarrage n'y changerait rien.
#
# Les confondre ferait echouer `docker compose up --wait` sur une pile parfaitement
# fonctionnelle dont les donnees ont vieilli, et pousserait Docker a redemarrer un
# conteneur qui va bien. Constate le 24/11/2026.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/meta', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "carburant_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
