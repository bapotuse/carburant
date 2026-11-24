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

# supercronic : un cron concu pour les conteneurs. Il ecrit sur stdout, propage le
# code de sortie, ne demande pas de PID 1 particulier, et n'avale pas les journaux
# dans /var/log comme le cron de Debian.
#
# Le binaire est telecharge depuis la page des publications GitHub et **verifie par
# son empreinte**. Les deux empreintes ci-dessous ont ete relevees le 24/11/2026 sur
# les binaires reellement telecharges ; une modification amont fera echouer la
# construction plutot que de passer inapercue.
#
# `TARGETARCH` est fourni par buildx : la meme ligne construit l'image amd64 et
# l'image arm64 (le VPS Oracle Ampere est aarch64).
ARG SUPERCRONIC_VERSION=0.2.51
ARG TARGETARCH
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) empreinte=cc232108374e8e2b537045f2d5eaa1229f619db314c3ba6a14d38b35dc0aa123 ;; \
      arm64) empreinte=4ae22576a78223d8ccdf5f3b3660a5cbb5288416bf0ca96afc4a36d195932b94 ;; \
      *) echo "architecture non prevue : ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}"; \
    python -c "import urllib.request,sys; urllib.request.urlretrieve(sys.argv[1], '/tmp/supercronic')" "$url"; \
    echo "${empreinte}  /tmp/supercronic" | sha256sum -c -; \
    chmod +x /tmp/supercronic; \
    mv /tmp/supercronic /usr/local/bin/supercronic; \
    supercronic -version

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

# Les migrations : c'est le conteneur etl qui les applique (`etl migrate`), au
# demarrage de la pile comme au deploiement.
COPY infra/migrations/ infra/migrations/

# La table de planification, lue par supercronic en production.
COPY infra/cron/carburant.cron infra/cron/carburant.cron

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

# Par defaut, une collecte et on sort : c'est ce que fait `make etl`. En production,
# compose.prod.yaml remplace cette commande par supercronic, qui la rejoue toutes les
# quinze minutes. En developpement, personne ne veut que `make up` se mette a
# interroger la vraie source en boucle.
CMD ["etl", "run"]
