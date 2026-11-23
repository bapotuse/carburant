# Spécification — infrastructure et production

## Local
- Docker Compose : `db` (PostgreSQL ≥ 16 + PostGIS, dernière version majeure disponible pour l'architecture cible), `etl`, `api`, `web`, plus `caddy` en production. Healthcheck sur chaque service, utilisateurs non-root, base jamais exposée hors du réseau Docker.
- Noms de projet, réseaux et volumes préfixés : le VPS hébergera aussi d'autres projets de Baptiste (un projet de mini-jeux est prévu). Ne suppose jamais que le projet est seul sur la machine.

## VPS Oracle Cloud (Free Tier, créé en novembre 2026, encore vide)
- Vérifie d'abord l'architecture (`uname -m` : aarch64 sur une instance Ampere A1) et les ressources (`free -h`, `df -h`). Adapte-toi : images multi-architecture (buildx amd64 + arm64) construites en CI et publiées sur GHCR ; si la RAM est faible (instance micro), swap, réglages Postgres réduits et aucun build sur le VPS.
- L'image officielle `postgis/postgis` n'a longtemps été publiée que pour amd64 : vérifie sa disponibilité en arm64 ; sinon, image multi-architecture reconnue ou image Postgres officielle + paquet PostGIS. Choix noté dans decisions.md.
- Réseau : ouvrir 80 et 443 à deux niveaux. D'une part la liste de sécurité (ou le NSG) du VCN dans la console Oracle : action de Baptiste, à guider. D'autre part le pare-feu de l'instance : les images Ubuntu d'Oracle embarquent des règles iptables restrictives. SSH par clé uniquement.
- Accès : Baptiste te donne l'IP et l'utilisateur ; tu crées un alias dans `~/.ssh/config` (par exemple `carburant-vps`) et tu travailles par ssh.

## Caddy
Reverse proxy partagé (un bloc par site, pour accueillir les autres projets), HTTPS automatique (il faut un nom de domaine qui pointe vers l'IP ; sans domaine, propose un sous-domaine gratuit type DuckDNS), compression, en-têtes de sécurité (CSP compatible avec MapLibre et ses workers), cache long des assets versionnés. Routes : site, API, `/mcp` pour le serveur MCP HTTP.

## CI/CD (GitHub Actions)
- À chaque push et PR : lint, typage, tests Python (avec un service PostGIS), tests front, Playwright, Lighthouse CI en profil mobile, vérification que le client API généré est à jour.
- Sur `main` : build des images multi-architecture, publication sur GHCR.
- Déploiement : `make deploy` (ssh, `docker compose pull && docker compose up -d`, migrations, smoke test). Automatisable via Actions si Baptiste ajoute la clé de déploiement aux secrets du dépôt (à guider).
- Compte GitHub de Baptiste : `bapotuse`. Création du dépôt avec `gh` si Baptiste a fait `gh auth login` (à guider), sinon création manuelle guidée.

## Exploitation
- ETL planifié toutes les 15 min dans le conteneur etl.
- Sauvegardes : `pg_dump` quotidien compressé, rotation 7 quotidiennes + 4 hebdomadaires, copie hors du VPS (destination à choisir en cadrage), procédure de restauration écrite et exécutée une fois pour de vrai.
- Monitoring minimal : `/v1/sante` ; logs JSON sur stdout ; alerte si la collecte échoue ou si les données vieillissent, via un « dead man's switch » (par exemple healthchecks.io : l'ETL envoie un signal après chaque exécution réussie, et l'absence de signal alerte Baptiste par mail ou notification) ; surveillance de disponibilité de la page d'accueil par le même service.
- Sécurité : mises à jour de sécurité automatiques (unattended-upgrades), secrets dans un `.env` sur le VPS (droits 600), aucun port d'administration exposé.

## README final
Captures mobiles ; GIF de démo du MCP (Baptiste l'enregistre depuis son client : prépare-lui un script pas à pas) ; schéma d'architecture Mermaid ; section « Choix techniques et compromis » ; lancement en une commande ; liens vers le site et la documentation OpenAPI.
