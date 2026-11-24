# Avancement

## Prochaine action
**J1-5** : l'accueil mobile — champ d'adresse avec anti-rebond, bouton « Ma position »,
liste triée par prix, prix façon totem, dans le style de la planche.

L'API est prête et mesurée : `/v1/stations/proches` répond en **18,7 ms au p95** sur
200 requêtes réparties dans dix villes de France (cible : 300 ms).

J1-1 (téléchargement) et J1-2 (staging) sont faits et vérifiés sur les vraies données.
Ce qui suit, dans l'ordre :

1. ~~**J1-2** `staging`~~ ✅ fait le 24/11/2026.
2. ~~**J1-3** `marts`~~ ✅ fait le 24/11/2026 — idempotence prouvée sur les vraies
   données : au second passage, **0 prix inséré, 33 153 déjà connus**.
3. ~~**J1-4** API~~ ✅ fait le 24/11/2026 — `/v1/stations/proches`, `/v1/geocode`,
   `/v1/meta`, erreurs `problem+json`, `ETag` et `Cache-Control`. p95 **18,7 ms**.
4. **J1-5** Web : accueil mobile, champ d'adresse avec anti-rebond, « Ma position »,
   liste triée par prix, prix façon totem.
5. **J1-6** Déploiement : workflow GitHub Actions (images GHCR + ssh depuis le runner),
   Caddy, HTTPS, collecte planifiée par supercronic.

Rappel pour la reprise : lire `docs/reconnaissance.md` avant de toucher aux seuils, et
`docs/decisions.md` avant de refaire un choix déjà tranché.

Le Jalon 0 est terminé : `make up` et `make check` verts sur machine propre, dépôt
poussé sur https://github.com/bapotuse/carburant, **CI verte sur les 3 jobs**.
Seule la paire typographique reste formellement ouverte : la paire B est appliquée par
défaut, les paires A et C restent visibles sur `/planche-de-style` et en changer ne
coûte que trois lignes.

## En attente de Baptiste

| # | Action | Débloque | Statut |
|---|---|---|---|
| 1 | Dépôt GitHub + application Claude installée dessus | J0-12, J0-14 | ✅ fait le 23/11/2026 |
| 2 | IP et utilisateur du VPS | Jalon 1 : déploiement | ✅ `opc@144.24.195.97` (Oracle Linux) |
| 3 | **Ports 80 et 443 dans la *security list* du VCN Oracle** | mise en ligne du Jalon 1 | ⏳ instructions données le 23/11, il ne savait pas où cliquer |
| 4 | **Nom de domaine** — il n'en a pas. Option a : acheter un `.fr` (~7 €/an, recommandé). Option b : sous-domaine gratuit DuckDNS. Sans domaine, pas de HTTPS, donc **pas de géolocalisation testable sur son iPhone** | mise en ligne du Jalon 1 | ⏳ en attente de son choix |
| 5 | Trois secrets GitHub pour le déploiement (`VPS_HOST`, `VPS_USER`, clé privée) | fin du Jalon 1 | 🔜 à demander quand le workflow sera écrit |
| 6 | Compte healthchecks.io | Jalon 6 : alertes | 🔜 plus tard |
| 7 | Compte PyPI + 2FA | Jalon 4 : `uvx prix-carburant-mcp` | 🔜 plus tard |

**Validation de goût encore ouverte** : la paire typographique. La **paire B**
(Newsreader + Source Sans 3) est appliquée par défaut faute d'objection ; les paires A
et C restent déclarées et visibles sur `/planche-de-style`. En changer coûte trois
lignes dans `web/app/styles/tokens.css` plus le préchargement dans `nuxt.config.ts`.

**Rien de tout cela ne bloque le travail du Jalon 1** jusqu'à sa mise en ligne.

## Jalons
Chaque jalon se termine par : critère de sortie vérifié, bilan à Baptiste, mise à jour de comprendre-le-projet.md.

### J0 — Socle

Dans l'ordre. Chaque tâche a sa commande de vérification ; une tâche n'est cochée que si la
commande a été lancée et son résultat observé (`CLAUDE.md` § « Terminé = observé »).

Légende : ✅ fait et vérifié · ⏳ écrit, en attente d'une action de Baptiste ·
🎨 en attente de validation de goût.

| # | Tâche | Commande de vérification |
|---|---|---|
| J0-1 ✅ | Arborescence `etl/ api/ web/ mcp/ infra/ docs/ data/`, `.gitignore` (dont `.env`, `data/raw/`, `node_modules/`, `.venv/`), `.env.example` | `test -d etl -a -d api -a -d web -a -d mcp -a -d infra && git check-ignore -v .env` |
| J0-2 ✅ | Workspace uv : `pyproject.toml` racine avec `[tool.uv.workspace]`, membres `etl`, `api`, `mcp` ; `requires-python = ">=3.14"` | `uv sync && uv run python -c "import sys; assert sys.version_info[:2]==(3,14), sys.version"` |
| J0-3 ✅ | `web/` en pnpm : Nuxt 4.6.4, Vue 3, TypeScript strict, **sans** librairie de composants ni Tailwind | `cd web && pnpm install && pnpm build && grep -c '"@nuxt/ui"\|tailwind' package.json` → 0 |
| J0-4 ✅ | Docker Compose : `db` (PostGIS), `etl`, `api`, `web`. Healthcheck par service, utilisateurs non-root, `db` non exposée hors du réseau Docker, noms de projet/réseaux/volumes **préfixés `carburant_`** | `docker compose config --quiet && docker compose ps --format '{{.Service}} {{.Health}}'` → tous `healthy` |
| J0-5 ✅ | Migration 001 : schémas `raw`, `staging`, `marts`, `meta` + `CREATE EXTENSION postgis`. Outil de migration : choix noté dans `decisions.md` | `make migrate && docker compose exec -T db psql -U carburant -tAc "select string_agg(nspname,',' order by nspname) from pg_namespace where nspname in ('raw','staging','marts','meta')"` → `marts,meta,raw,staging` |
| J0-6 ✅ | Makefile : `up`, `down`, `etl`, `test`, `check`, `captures`, `deploy`, `migrate`, `logs` | `make -n up down etl test check captures deploy migrate logs` (aucune cible manquante) |
| J0-7 ✅ | Lint / format / typage Python : ruff (lint + format), mypy **strict** | `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict etl api mcp` |
| J0-8 ✅ | Lint / format / typage front : eslint 10, prettier, `vue-tsc --noEmit` | `cd web && pnpm lint && pnpm format:check && pnpm typecheck` |
| J0-9 ✅ | `pre-commit` pour les deux côtés (ruff, mypy, eslint, prettier, détection de secrets) | `pre-commit run --all-files` |
| J0-10 ✅ | Un test par brique, qui échoue si la brique est cassée : helper de format français (`1,879 €`, `23 nov.`, espaces insécables) côté Python, un test Vitest, un test Playwright de démarrage | `make test` |
| J0-11 ✅ | `make check` = lint + format + typage + tests, des deux côtés, en une commande | `make check` → sortie 0 |
| J0-12 ✅ | CI GitHub Actions : lint, typage, tests Python avec un service PostGIS, tests front, sur push et PR | `gh run list --limit 1` → `success` (après J0-14) |
| J0-13 ✅ | README squelette : schéma d'architecture Mermaid, lancement en une commande, liens | `grep -q '```mermaid' README.md && grep -q 'make up' README.md` |
| J0-14 ✅ | Dépôt distant `bapotuse/carburant` créé, `main` poussée, CI verte | `git push -u origin main && gh run watch` |
| J0-15 🎨 | **[VALIDATION]** Planche de style : page statique rendant 2 ou 3 paires typographiques × palette claire et sombre × prix façon totem × jauge × ticket de caisse. Valeurs d'exemple **étiquetées comme telles**. Un test automatisé vérifie le contraste de chaque paire de tokens réellement utilisée | `make captures` puis ouverture des captures de `docs/captures/J0/` (iPhone SE 375×667, Pixel 7, bureau 1440×900, thèmes clair et sombre) et comparaison à `docs/anti-patterns-ia.md` |

Notes d'exécution :

- **J0-5** : les partitions de `fact_prix` ne sont pas créées au J0 (c'est du J1), mais la migration
  pose déjà la contrainte de bornes **en UTC** et la partition DEFAULT, à cause du piège mesuré
  (`docs/reconnaissance.md` § 2.5).
- **J0-3** : `@tresjs/nuxt` est explicitement **exclu** (il tire `@nuxt/ui`, interdit). La 3D
  arrivera via `@tresjs/core` + `three`, au J5.
- **J0-12 / J0-14** : dépendent d'une action de Baptiste (`gh auth login` ou création manuelle du
  dépôt). Tout le reste du J0 se fait sans lui.
- **J0-15** est le seul arrêt du jalon. Les tâches J0-1 à J0-14 s'enchaînent sans feu vert.

Sortie : `make up && make check` vert sur une machine propre ; CI verte sur GitHub ; captures de la
planche de style produites et relues.

**Constaté le 23/11/2026 :**

- `make up` **sur une base vierge** → `db`, `api`, `web` sains ; migration 001
  appliquee ; PostGIS 3.7.0 ; les quatre schemas crees ; `/v1/sante` repond **200**
  base allumee, **503** base eteinte (verifie en l'arretant), et **503 avec
  `schema_pret: false`** si les migrations ne sont pas passees ; `/docs` repond 200 ;
  le site rend « Où faire le plein ? ».
- `make migrate` relance → « Base a jour : aucune migration a appliquer ». Et si un
  fichier deja applique est modifie, le script s'arrete en le disant plutot que de
  laisser deux bases diverger.
- `make check` → lint, formatage, typage strict et **221 tests** (112 Python + 109 front)
  au vert.
- `make captures` → 30 captures sur 3 appareils × 2 themes, compressees de 28,4 Mo a
  6,1 Mo, dans `docs/captures/J0/`, relues contre `docs/anti-patterns-ia.md`.
- `pre-commit run --all-files` → 14 hooks au vert.
- **CI GitHub verte** sur les 3 jobs (Python avec service PostGIS, front, pre-commit) :
  https://github.com/bapotuse/carburant/actions/runs/45232820226
- **Non verifie** : le comportement reel sur iOS (voir `docs/a-verifier.md`, ligne 15).

### J1 — Tranche verticale en ligne
- [ ] ETL minimal : extract (export du flux v2) → raw → staging → `dim_station` + `fact_prix` (grain = changement de prix, idempotent)
- [ ] API : `/v1/stations/proches`, `/v1/geocode`, `/v1/sante`
- [ ] Web : accueil mobile (adresse ou position → liste triée par prix, prix façon totem), dans le style validé sur la planche
- [ ] Déploiement sur le VPS, Caddy, HTTPS, collecte planifiée

Sortie : depuis un téléphone, l'URL publique → « le Prado, Marseille » → stations réelles avec prix et fraîcheur ; deux exécutions successives de l'ETL ne créent aucun doublon.

### J2 — ETL complet
- [ ] Toutes les règles de transformation (normalisation, aberrants, fraîcheur, ruptures, déduplication), testées
- [ ] Partitionnement mensuel, création automatique des partitions
- [ ] `snapshot_prix_jour` et vues agrégées
- [ ] `ref_facteur_emission` depuis l'API ADEME, versionnée
- [ ] Enseignes via OpenStreetMap (si validé), taux de correspondance mesuré
- [ ] Amorçage de l'historique depuis les archives (périmètre validé), en streaming
- [ ] Contrôles qualité à chaque exécution, journal `meta.execution_etl`
- [ ] Revue `revue-donnees` sans écart bloquant
- [ ] Proposition dbt dans le bilan

Sortie : tests verts ; rapport qualité de la dernière exécution ; volumes réels notés.

### J3 — API complète
- [ ] Tous les endpoints, OpenAPI documentée, client TypeScript généré
- [ ] « Meilleure station » avec tests unitaires, de propriétés et d'intégration
- [ ] Cache, rate limiting, CORS, erreurs problem+json

Sortie : `/docs` lisible et complet ; tests verts ; p95 < 300 ms sur le VPS pour `/stations/proches`.

### J4 — Serveur MCP
- [ ] [VALIDATION] Nom du package
- [ ] Package, tools, transport stdio, transport Streamable HTTP déployé
- [ ] Tests en mémoire et smoke test MCP Inspector en mode CLI
- [ ] README avec 5 conversations réelles

Sortie : `uvx …` fonctionne depuis une machine propre ; la question du Prado obtient une réponse juste via un vrai client MCP, en local et en distant.

### J5 — Site complet
- [ ] [VALIDATION] Maquettes mobiles de l'accueil et de la carte (captures)
- [ ] Pages : carte avec bottom sheet, fiche station, tendances, empreinte carbone, comprendre le prix, à propos, 404, erreur, hors ligne
- [ ] Détails « univers carburant » retenus
- [ ] [VALIDATION] Objets 3D (descriptions ou croquis, puis prototype de l'objet retenu)
- [ ] 3D avec replis statiques
- [ ] PWA et mode hors ligne
- [ ] Anecdotes calculées et éditoriales sourcées
- [ ] Revue `revue-design` sans écart bloquant

Sortie : Lighthouse mobile ≥ 90 dans les 4 catégories sur chaque page (CI) ; aucune violation axe ; parcours Playwright principaux verts sur iPhone SE, Pixel 7 et bureau ; captures dans `docs/captures/J5/`.

### J6 — Production et présentation
- [ ] Sauvegardes, restauration testée pour de vrai
- [ ] Alerte en cas d'échec de collecte ou de données trop vieilles
- [ ] README final (captures, GIF, architecture, choix et compromis)
- [ ] comprendre-le-projet.md complet, avec les questions de recruteur

Sortie : Baptiste peut présenter le projet avec l'URL, le dépôt et le document de compréhension.

## Journal

- **2026-11-24 — Jalon 1, étape 4 : l'API.** `/v1/stations/proches` (tri par prix ou
  distance, filtre carburant, pagination), `/v1/geocode` (proxy Géoplateforme, cache
  24 h, limitation de débit sortante, **règle d'ambiguïté**), `/v1/meta`, erreurs
  `application/problem+json`, `ETag` et `Cache-Control`.
  **Mesuré sur les vraies données** : p95 **18,7 ms** sur 200 requêtes dans dix villes
  de France, médiane 10,4 ms, max 65,5 ms. Cible : 300 ms.
  La règle d'ambiguïté du géocodage est **vérifiée contre le vrai service IGN** : les
  quatre verdicts de la reconnaissance tiennent toujours.
  **Défaut grave trouvé en regardant `/v1/meta`** : il annonçait qu'aucune collecte
  n'avait jamais réussi alors que les données étaient bien chargées. Cause — en mode
  non-autocommit, psycopg ouvre une transaction dès le premier `SELECT` ; le contrôle
  de la partition DEFAULT, placé entre le chargement et la clôture de l'exécution,
  transformait les blocs suivants en simples points de reprise, et le `close()`
  annulait la clôture. Corrigé en `autocommit=True` avec transactions explicites, et
  verrouillé par un test de non-régression.
  Deux autres défauts trouvés par des tests : `count(DISTINCT …) OVER ()` n'existe pas
  dans PostgreSQL, et comparer deux scores de géocodage en flottants bruts bascule du
  mauvais côté de la borne (`0,95 − 0,90` vaut `0,04999…`).
  **326 tests** : 172 unitaires Python, 109 front, 39 d'intégration, 6 contre les
  vraies sources.

- **2026-11-24 — Jalon 1, étape 3 : le modèle d'exposition.** `marts.dim_station`
  (geography + index GiST, autoroute dérivée de `pop`, SCD de type 1),
  `marts.fact_prix` partitionnée par mois avec le grain « un changement de prix »,
  `marts.rupture` pour l'état courant, `marts.dim_carburant`.
  **Critère de sortie du jalon atteint** : deux exécutions successives sur les vraies
  données donnent **0 prix inséré et 33 153 déjà connus** au second passage, et
  9 825 stations mises à jour en place. Partition DEFAULT : **0 ligne**.
  Chargé en vrai : 9 825 stations, 33 153 changements de prix, 22 186 ruptures,
  **15 partitions** de juillet 2025 à décembre 2026.
  Requête « stations proches » mesurée à **11 ms** : les cinq gazoles les moins chers
  autour du Prado sortent avec leur adresse, leur prix et l'heure de mise à jour.
  **Écart avec la spec corrigé** : « partitions du mois courant et du suivant » était
  insuffisant — `maj` est une date de changement qui remonte à plus d'un an, et deux
  mois de partitions auraient mis plus de mille lignes dans la partition DEFAULT.
  **Défauts trouvés par les tests** : PostgreSQL refuse les paramètres liés dans du
  DDL, et refuse `RETURNING (xmax = 0)` dans une CTE. Deux de mes tests étaient faux
  (deux prix du même carburant dans une seule collecte, ce que le flux ne produit
  jamais) : corrigés, pas désactivés.

- **2026-11-24 — Jalon 1, étapes 1 et 2.** Téléchargement du flux (réessais, empreinte
  dans le nom de fichier, purge), validation pydantic à la frontière raw → staging,
  aplatissement au format long, chargement par `COPY`, migrations en Python,
  commande `etl run` complète avec journal dans `meta.execution_etl`.
  **Vérifié sur les vraies données** : 9 825 stations, 55 339 lignes de prix
  (33 153 prix + 22 186 ruptures), **5 rejets** — tous des prix E85 à 1,99 €, soit
  exactement les erreurs de saisie que la reconnaissance avait identifiées.
  Chaîne complète constatée : `make up` sur base vierge → `etl run` → `/v1/sante`
  annonce « il y a 0 minute ». Médianes en base conformes à la reconnaissance
  (gazole 2,099, E85 0,869, GPLc 1,075).
  **Défauts trouvés par des tests, pas par relecture** : deux collectes dans la même
  seconde s'écrasaient (l'empreinte est désormais dans le nom) ; les fichiers de
  migration ouvraient leur propre transaction et cassaient celle du lanceur ; le
  répertoire des migrations déduit d'un nombre de dossiers parents échouait en
  silence dans l'image ; le pool HTTP réessayait sur une connexion morte.
  269 tests verts (160 Python + 109 front), plus 11 tests d'intégration contre une
  vraie base PostGIS et 2 tests contre la vraie source.

- **2026-11-23 — Jalon 0, socle.** Monorepo complet : workspace uv (Python 3.14,
  3 paquets), front Nuxt 4.6.4 en pnpm (Node 26), Docker Compose a 5 services avec
  healthchecks et volumes prefixes, migration 001 (schemas raw/staging/marts/meta +
  PostGIS + `meta.execution_etl`), Makefile, ruff + mypy strict, eslint + prettier +
  vue-tsc, pre-commit (14 hooks dont gitleaks), CI GitHub Actions a 3 jobs, README avec
  schema Mermaid, `docs/comprendre-le-projet.md`.
  Code reel ecrit, teste : normalisation des carburants, lecture des horodatages avec
  le piege du fuseau, classement de fraicheur, detection d'aberrants avec plancher de
  MAD, formateurs francais (Python et `Intl`), `/v1/sante` qui interroge vraiment la
  base, composants PrixTotem / PastilleCarburant / JaugeAutonomie / TicketPlein, et la
  planche de style.
  **Verifie** : `make up` (db/api/web sains, migration appliquee, 200 puis 503 en
  coupant la base, puis 200 au redemarrage), `make check` (221 tests), `make captures`
  (30 captures, 3 appareils × 2 themes, compressees de 28,4 a 6,1 Mo), `pre-commit
  --all-files`. JS client mesure : **77,7 Ko gzip** pour tout le site, budget 100 Ko.
  **Corrections nees de tests qui ont echoue** : `--fraicheur-perime` etait a 3,4:1 au
  lieu de 4,5:1 ; `role="text"` n'existe pas en ARIA ; Fraunces n'a pas de chiffres
  tabulaires et est eliminee ; TypeScript 7 casse `typescript-eslint` ; PostgreSQL 18+
  a change de point de montage ; `corepack` a disparu de Node 26.
  **Non fait** : push et CI (en attente du depot distant), validation de la planche de
  style (en attente de Baptiste).

- **2026-11-23 — Session de cadrage.** Spécification persistée en 8 fichiers et commitée (`docs:
  spécification initiale`). Reconnaissance par vraies requêtes sur les 4 sources : flux v2
  (export complet, 9 826 stations, 47 champs), source amont roulez-eco (XML ISO-8859-1), archives
  annuelles (16 années téléchargées, 2007 à 2026), Base Carbone ADEME, géocodage Géoplateforme,
  tuiles OpenFreeMap. 5 hôtes ajoutés à la politique réseau de l'environnement.
  **Vérifié par mesure** : fuseau horaire du flux = heure locale Paris malgré le suffixe `+00:00`
  (r = 0,9987 entre les profils horaires de janvier et juillet sur 5,3 M d'horodatages) ;
  5 297 799 changements de prix en 2025 ; chargement réel dans PostgreSQL 18.7 + PostGIS
  (`COPY` 14,0 s, 307 Mo de données + 232 Mo d'index pour un an, requête `ST_DWithin` 10 km +
  dernier prix par station en 13,7 ms) ; `postgis/postgis` toujours sans image arm64 ; API ADEME
  migrée sur Data Fair (l'ancienne répond 410) ; mapping des 6 carburants vers 5 éléments ADEME,
  ordres de grandeur de la spec confirmés à moins de 2,2 % près ; règle de prix aberrants de la spec
  recalibrée (plancher de MAD à 0,05 €). Rédigé `reconnaissance.md`, `anti-patterns-ia.md`
  (96 signes), `propositions-design.md`, `decisions.md` (28 décisions), `a-verifier.md` (14 points),
  détail du Jalon 0 (15 tâches avec commande de vérification).
  **Aucun code applicatif écrit**, conformément à la consigne de cadrage.
