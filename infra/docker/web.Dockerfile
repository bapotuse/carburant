# syntax=docker/dockerfile:1
# Front Nuxt en SSR.
FROM node:26-trixie-slim AS build

# Certificats d'autorite supplementaires. Le dossier est vide en temps normal : il
# n'existe que pour les environnements de construction derriere un proxy qui termine
# le TLS (voir infra/docker/ca/README.md).
#
# L'image node n'a aucun magasin de certificats systeme -- pas meme /etc/ssl/certs :
# Node embarque le sien. Le seul levier est donc NODE_EXTRA_CA_CERTS, qui attend un
# fichier ne contenant QUE les certificats supplementaires. S'il n'y en a aucun, le
# fichier n'est pas cree et la variable n'est pas posee, pour que Node n'affiche pas
# d'avertissement a chaque appel.
COPY infra/docker/ca /tmp/ca-supplementaires
RUN set -eux; \
    mkdir -p /etc/ssl; \
    cat /tmp/ca-supplementaires/*.crt > /etc/ssl/carburant-extra.crt 2>/dev/null || true; \
    if [ ! -s /etc/ssl/carburant-extra.crt ]; then rm -f /etc/ssl/carburant-extra.crt; fi; \
    rm -rf /tmp/ca-supplementaires

# corepack a ete retire de Node a partir de la version 25 : on installe pnpm
# directement, a la version exacte declaree dans web/package.json.
ARG PNPM_VERSION=10.20.0
RUN npm install -g "pnpm@${PNPM_VERSION}"

WORKDIR /app

COPY web/package.json web/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    set -eux; \
    if [ -f /etc/ssl/carburant-extra.crt ]; then \
        export NODE_EXTRA_CA_CERTS=/etc/ssl/carburant-extra.crt; \
    fi; \
    pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# ---- image finale : seulement la sortie de build et le runtime Node
FROM node:26-trixie-slim AS runtime
ENV NODE_ENV=production \
    NITRO_PORT=3000 \
    NITRO_HOST=0.0.0.0
WORKDIR /app
COPY --from=build /app/.output ./.output
RUN useradd --system --uid 10004 carburant
USER carburant
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", ".output/server/index.mjs"]
