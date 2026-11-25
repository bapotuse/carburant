#!/usr/bin/env bash
# Prepare le VPS : Docker, pare-feu de l'instance, swap, repertoire et .env.
#
# Lance par le workflow de deploiement avant chaque deploiement, pas a la main.
# Il est **idempotent** : le rejouer sur une machine deja prete ne change rien, et
# surtout ne regenere pas le mot de passe de la base.
#
# La machine visee est une instance Oracle Cloud sous Oracle Linux (utilisateur
# `opc`, pare-feu `firewalld`, gestionnaire de paquets `dnf`).
set -euo pipefail

# L'adresse publique du site, schema compris : http://144.24.195.97 pendant la
# periode sans nom de domaine, https://quelquechose.fr ensuite. Tout le reste en
# decoule, pour qu'il n'y ait qu'une seule valeur a changer le jour du basculement.
SITE_URL="${SITE_URL:?SITE_URL manquant}"
# Une barre oblique finale donnerait des adresses a double barre (`https://x//v1/…`)
# du cote du navigateur. On la retire une bonne fois.
SITE_URL="${SITE_URL%/}"

RACINE="${RACINE:-/opt/carburant}"

titre() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

# --------------------------------------------------------------- la machine
titre "La machine"
# Releve a chaque fois : c'est ce qui decide de l'image PostGIS et de la necessite
# d'un swap. Voir docs/specs/infra.md.
architecture=$(uname -m)
echo "architecture : $architecture"
echo "noyau        : $(uname -r)"
grep -E '^(NAME|VERSION)=' /etc/os-release || true
free -h || true
df -h / || true

# --------------------------------------------------------------- Docker
titre "Docker"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    echo "Deja installe : $(docker --version)"
else
    echo "Installation depuis le depot officiel Docker."
    depot=https://download.docker.com/linux/centos/docker-ce.repo
    sudo dnf install -y dnf-plugins-core
    # dnf 4 (Oracle Linux 8 et 9) et dnf 5 n'ont pas la meme commande pour ajouter
    # un depot. On essaie l'ancienne, puis la nouvelle : la version de l'image de
    # l'instance n'est pas connue a l'avance.
    sudo dnf config-manager --add-repo "$depot" \
        || sudo dnf config-manager addrepo --from-repofile="$depot"
    # `--allowerasing` : les images Oracle Linux embarquent podman et runc, qui
    # entrent en conflit avec containerd.io. On laisse dnf faire la substitution
    # plutot que d'echouer sur un conflit de fichiers.
    sudo dnf install -y --allowerasing \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo systemctl enable --now docker
# Confort pour Baptiste quand il se connecte a la main : il pourra taper `docker ps`
# sans sudo (a sa prochaine connexion, l'appartenance a un groupe n'etant lue qu'a
# l'ouverture de session). Le deploiement, lui, passe toujours par sudo : il ne doit
# pas dependre de l'ordre des connexions.
sudo usermod -aG docker "$USER"
sudo docker --version
sudo docker compose version

# --------------------------------------------------------------- pare-feu
titre "Pare-feu de l'instance"
# Deux niveaux a ouvrir : la liste de securite du VCN, dans la console Oracle, et
# le pare-feu de la machine. Ce script ne peut agir que sur le second.
if systemctl is-active --quiet firewalld; then
    sudo firewall-cmd --permanent --add-service=http --quiet || sudo firewall-cmd --permanent --add-service=http
    sudo firewall-cmd --permanent --add-service=https --quiet || sudo firewall-cmd --permanent --add-service=https
    sudo firewall-cmd --reload
    echo "firewalld : $(sudo firewall-cmd --list-services)"
else
    echo "firewalld n'est pas actif. Rien a ouvrir ici."
fi

# --------------------------------------------------------------- swap
titre "Memoire"
memoire_mo=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
swap_mo=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)
echo "RAM : ${memoire_mo} Mo, swap : ${swap_mo} Mo"
if [ "$memoire_mo" -lt 2048 ] && [ "$swap_mo" -lt 512 ]; then
    # Une instance micro a 1 Go. PostgreSQL et Node y tiennent, mais un pic pendant
    # une collecte suffit a faire tuer un conteneur par le noyau. Deux gigaoctets de
    # swap coutent 2 Go de disque et evitent cela.
    echo "Peu de RAM et pas de swap : creation d'un fichier d'echange de 2 Go."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    free -h
fi

# --------------------------------------------------------------- configuration
titre "Repertoire et configuration"
sudo mkdir -p "$RACINE"
sudo chown "$USER:$USER" "$RACINE"
cd "$RACINE"

# Le mot de passe de la base est tire au sort **sur la machine**, une seule fois. Il
# n'existe ni dans le depot, ni dans les secrets GitHub, ni dans aucun journal.
if [ -f .env ] && grep -q '^POSTGRES_PASSWORD=' .env; then
    motdepasse=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
    echo "Mot de passe de la base : deja en place, conserve."
else
    motdepasse=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-28)
    echo "Mot de passe de la base : tire au sort."
fi

# Tout decoule de SITE_URL. En HTTPS, Caddy a besoin du nom pour obtenir son
# certificat ; en HTTP, `:80` lui dit de servir en clair sur le port 80, ce qui est
# le mode utilise tant qu'il n'y a pas de nom de domaine.
schema=${SITE_URL%%://*}
hote=${SITE_URL#*://}
hote=${hote%%/*}
if [ "$schema" = "https" ]; then
    domaine="$hote"
else
    domaine=":80"
fi
echo "Site : $SITE_URL  (Caddy ecoutera sur « $domaine »)"

# La meme image qu'en developpement, quelle que soit l'architecture : une base de
# production sur PostGIS 3.6 et un developpement sur 3.7, c'est du SQL ecrit contre
# une version et execute contre une autre. imresamu/postgis est multi-architecture
# (le VPS est un Ampere aarch64, pour lequel postgis/postgis ne publie rien).
image_db="imresamu/postgis:18-3.6-alpine"
echo "Image de la base : $image_db (architecture : $architecture)"

cat > .env <<FIN
# Genere par infra/scripts/preparer-le-vps.sh. Reecrit a chaque deploiement, sauf
# POSTGRES_PASSWORD qui est conserve d'une fois sur l'autre.

POSTGRES_USER=carburant
POSTGRES_PASSWORD=$motdepasse
POSTGRES_DB=carburant
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql://carburant:$motdepasse@db:5432/carburant

ETL_USER_AGENT=carburant/0.1 (+https://github.com/bapotuse/carburant)
ETL_RETENTION_JOURS=14

API_ORIGINES_AUTORISEES=$SITE_URL
API_CACHE_PRIX_SECONDES=900
API_CACHE_GEOCODE_SECONDES=86400
API_CACHE_TENDANCES_SECONDES=3600
API_SANTE_AGE_MAX_MINUTES=60

CARBURANT_DOMAINE=$domaine
NUXT_PUBLIC_API_BASE=$SITE_URL
CARBURANT_API_BASE=http://api:8000/v1

IMAGE_DB=$image_db
FIN
chmod 600 .env
echo "$RACINE/.env ecrit, droits 600."

# --------------------------------------------------------------- ports 80 et 443
titre "Qui ecoute sur 80 et 443"
# Le VPS est destine a heberger plusieurs projets : il faut savoir ce qui occupe
# deja ces ports avant que Caddy n'essaie de les prendre. Le 25/11/2026, un service
# inconnu tenait le port 80 et faisait echouer le demarrage de Caddy.
sudo ss -ltnp "( sport = :80 or sport = :443 )" 2>/dev/null | sed 's/^/  /' || true

# Si ce n'est pas notre Caddy, on veut savoir ce que c'est avant d'y toucher : le
# VPS peut deja heberger autre chose, et rien ne sera arrete sans le demander.
if ! sudo ss -ltnp "( sport = :80 )" 2>/dev/null | grep -q .; then
    echo "  Le port 80 est libre."
elif ! sudo ss -ltnp "( sport = :80 )" 2>/dev/null | grep -q docker; then
    echo "  Un service hors Docker tient le port 80. Ce qu'il sert :"
    curl -sS -o /dev/null -w '    GET http://127.0.0.1/ -> %{http_code}\n' http://127.0.0.1/ || true
    sudo nginx -T 2>/dev/null \
        | grep -nE '^\s*(server_name|root|proxy_pass|listen|# configuration file)' \
        | head -30 | sed 's/^/    /' || true
fi

# --------------------------------------------------------------- anti-force-brute
titre "fail2ban"
# Affiche a chaque deploiement, pour qu'un bannissement du runner se voie dans le
# journal au lieu de ressembler a une panne reseau.
if systemctl is-active --quiet fail2ban 2>/dev/null; then
    sudo fail2ban-client status sshd 2>&1 | sed 's/^/  /' || true
else
    echo "fail2ban n'est pas actif."
fi

titre "Pret"
echo "La machine est prete a recevoir le deploiement."
