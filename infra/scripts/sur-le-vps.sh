#!/usr/bin/env bash
# Deploiement, execute SUR LE VPS.
#
# Ce script n'est jamais lance a la main : le workflow .github/workflows/
# deploiement.yml le copie sur le VPS et l'execute par ssh. Il suppose que
# /opt/carburant contient deja un fichier .env, cree une seule fois par Baptiste.
#
# Il est idempotent : le rejouer sur une machine deja a jour ne casse rien.
set -euo pipefail

RACINE=/opt/carburant
cd "$RACINE"

compose() { docker compose -f compose.prod.yaml "$@"; }

titre() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

titre "La machine"
# Releve a chaque deploiement : c'est ce qui decide de l'image PostGIS, des reglages
# de Postgres et de la necessite d'un swap. Voir docs/specs/infra.md.
echo "architecture : $(uname -m)"
echo "noyau        : $(uname -r)"
free -h || true
df -h "$RACINE" || true
docker --version
docker compose version

titre "Verification de la configuration"
test -f .env || { echo "Il manque $RACINE/.env sur le VPS." >&2; exit 1; }
# Droits 600 : le fichier porte le mot de passe de la base.
chmod 600 .env
compose config --quiet
echo "compose.prod.yaml et .env sont lisibles et coherents."

titre "Recuperation des images"
compose pull --quiet

titre "Base de donnees"
compose up -d --wait db

titre "Migrations"
# `run --rm` et non `exec` : le conteneur etl tourne en planificateur, et on ne veut
# pas d'une migration qui depende de son bon demarrage.
compose run --rm --no-deps etl etl migrate

titre "Demarrage de la pile"
# `--wait` attend que les healthchecks passent au vert, et echoue sinon : sans cela,
# un deploiement casse se terminerait en « succes ».
compose up -d --wait --remove-orphans

titre "Verification"
# Depuis l'interieur du reseau Docker : a ce stade le DNS public ne pointe peut-etre
# pas encore sur la machine, et on veut savoir si la pile elle-meme repond.
sante=$(compose exec -T web node -e "
fetch('http://api:8000/v1/sante')
  .then(async (r) => { console.log(r.status, (await r.text()).slice(0, 300)) })
  .catch((e) => { console.log('injoignable', e.message); process.exit(1) })
")
echo "/v1/sante -> $sante"

accueil=$(compose exec -T caddy wget -qO- --server-response http://localhost/ 2>&1 | head -1 || true)
echo "Caddy -> ${accueil:-pas de reponse}"

titre "Etat final"
compose ps --format 'table {{.Service}}\t{{.Status}}'

titre "Menage"
# Les images remplacees s'accumulent vite sur un disque de VPS. On ne touche ni aux
# volumes ni aux conteneurs : uniquement aux images qui ne servent plus.
docker image prune -f >/dev/null
echo "Images inutilisees supprimees."
