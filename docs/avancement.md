# Avancement

## Prochaine action
**J2, les enseignes OpenStreetMap.** Le flux officiel ne donne ni nom ni enseigne :
le rapprochement spatial avec OpenStreetMap (`amenity=fuel`, tags `brand` et `name`)
est la piste retenue au cadrage. Commencer par une **vraie requete Overpass** avant
d'ecrire quoi que ce soit, et ajouter l'hote a la politique reseau de
l'environnement. Taux de correspondance a mesurer et a afficher ; sous un seuil, pas
de classement par enseigne.

Puis, dans l'ordre : l'amorcage complet des seize annees **sur le VPS** (ici il
serait perdu a la fin du conteneur), la revue `revue-donnees`, et la proposition dbt
dans le bilan de jalon.

**Fait et verifie au J2, le 26/11/2026 :**

1. **Les controles qualite.** Huit questions posees en SQL, chacune rendant un
   verdict et une mesure lisible. Deux niveaux : bloquant (execution en echec,
   processus en erreur) et avertissement. Un controle en echec ne rejette jamais les
   donnees chargees. Mesure sur les vraies donnees : **1,21 % de prix atypiques** sur
   25 359 prix frais, pile dans la fourchette de 0,4 a 2,5 % de la reconnaissance.
2. **La regle des prix atypiques**, qui existait en Python sans etre branchee, vit
   desormais en SQL a cote de la donnee, avec un test qui verifie que les deux
   implementations disent la meme chose.
3. **Les agregats journaliers** (`marts.agregat_prix_jour`), calcules sur les prix
   **en vigueur** et non sur les seuls prix modifies ce jour-la.
4. **Les facteurs d'emission de l'ADEME**, historises, avec un garde-fou qui refuse
   un facteur dont l'unite ou l'ordre de grandeur a change.
5. **L'amorcage de l'historique** : `etl backfill --annee AAAA`, en streaming.
   Charge en vrai : 2007 (862 528 prix, mediane gazole **1,075 EUR**) et 2022
   (5 043 144 prix, mediane **1,862 EUR**) -- les deux eres d'unite. Rejoue : zero
   ligne inseree. Partition DEFAULT : **0 ligne** sur 27 partitions.

**Trois defauts trouves en faisant tourner, pas en relisant** : le controle des prix
atypiques depassait 25 secondes (reference departementale desormais materialisee :
0,84 s) ; le parseur d'archives attrapait la mauvaise exception et un nom de
carburant inattendu aurait fait planter tout l'amorcage ; et deux de mes propres
tests etaient faux.

**Deux corrections de la spec, par mesure** : les noms de champs de la Base Carbone
portent les accents, et l'historique complet pesera **7,7 Go** pour **50 minutes** de
chargement, et non 6,5 Go pour 30 minutes (120,2 octets par ligne mesures contre 102
estimes). Le VPS a 17 Go libres : cela passe, sans marge pour un doublement.

**Le Jalon 1 est en ligne** : <https://carburant.144-24-195-97.sslip.io>, en HTTPS.

Rappel pour la reprise : lire `docs/reconnaissance.md` avant de toucher aux seuils, et
`docs/decisions.md` avant de refaire un choix deja tranche.

## En attente de Baptiste

| # | Action | Débloque | Statut |
|---|---|---|---|
| 1 | Dépôt GitHub + application Claude installée dessus | J0-12, J0-14 | ✅ fait le 23/11/2026 |
| 2 | IP et utilisateur du VPS | Jalon 1 : déploiement | ✅ `opc@144.24.195.97` (Oracle Linux) |
| 3 | Ports 80 et 443 dans la *security list* du VCN Oracle | mise en ligne | ✅ fait le 25/11/2026 |
| 4 | Nom de domaine | mise en ligne | ✅ `carburant.144-24-195-97.sslip.io`, gratuit et sans inscription. Un vrai `.fr` reste possible plus tard : une ligne à changer |
| 5 | Trois secrets GitHub `VPS_HOST`, `VPS_USER`, `VPS_CLE_PRIVEE` | mise en ligne | ✅ fait le 25/11/2026 |
| 8 | **Ouvrir le site sur son iPhone** et essayer « Ma position », en 4G et en wifi | confiance dans le parcours mobile réel | ⏳ demandé le 25/11 |
| 6 | Compte healthchecks.io | Jalon 6 : alertes | 🔜 plus tard |
| 7 | Compte PyPI + 2FA | Jalon 4 : `uvx prix-carburant-mcp` | 🔜 plus tard |

**Validation de goût encore ouverte** : la paire typographique. La **paire B**
(Newsreader + Source Sans 3) est appliquée par défaut faute d'objection ; les paires A
et C restent déclarées et visibles sur `/planche-de-style`. En changer coûte trois
lignes dans `web/app/styles/tokens.css` plus le préchargement dans `nuxt.config.ts`.

**Rien de tout cela ne bloque le Jalon 2**, qui commence maintenant.

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
- [x] ETL minimal : extract (export du flux v2) → raw → staging → `dim_station` + `fact_prix` (grain = changement de prix, idempotent) — 24/11/2026
- [x] API : `/v1/stations/proches`, `/v1/geocode`, `/v1/sante` — 24/11/2026, p95 18,7 ms
- [x] Web : accueil mobile (adresse ou position → liste triée par prix, prix façon totem) — 24/11/2026, captures dans `docs/captures/J1/`
- [x] Déploiement sur le VPS, Caddy, HTTPS, collecte planifiée — **en ligne le
      25/11/2026** sur <https://carburant.144-24-195-97.sslip.io>

Sortie : depuis un téléphone, l'URL publique → « le Prado, Marseille » → stations réelles avec prix et fraîcheur ; deux exécutions successives de l'ETL ne créent aucun doublon.
**Atteinte et constatée le 25/11/2026**, le parcours étant rejoué contre la production
par le déploiement lui-même. Reste le test sur l'iPhone réel de Baptiste.

### J2 — ETL complet
- [x] Toutes les règles de transformation (normalisation, aberrants, fraîcheur, ruptures, déduplication), testées — 26/11/2026, la règle des prix atypiques désormais branchée et en SQL
- [x] Partitionnement mensuel, création automatique des partitions — 27 partitions sur l'amorçage, DEFAULT vide
- [x] ~~`snapshot_prix_jour`~~ `marts.agregat_prix_jour` et vues agrégées — 26/11/2026, grain revu et spec corrigée
- [x] `ref_facteur_emission` depuis l'API ADEME, versionnée — 26/11/2026, `etl facteurs`
- [ ] Enseignes via OpenStreetMap (si validé), taux de correspondance mesuré
- [x] Amorçage de l'historique depuis les archives, en streaming — 26/11/2026, `etl backfill`, deux années chargées pour de vrai. **Reste à lancer sur le VPS pour les seize années.**
- [x] Contrôles qualité à chaque exécution, journal `meta.execution_etl` — 26/11/2026, huit contrôles
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

- **2026-11-26 — Jalon 2 : qualite, agregats, ADEME, amorcage.** Cinq des neuf cases
  du jalon, en trois tranches commitees separement.
  **Les controles qualite**, ecrits en SQL, chacun rendant un verdict et une mesure
  lisible. Deux niveaux, bloquant et avertissement, et un controle en echec ne rejette
  jamais les donnees chargees : c'est l'execution qu'on marque.
  **La regle des prix atypiques** existait en Python depuis le Jalon 0 **sans etre
  branchee nulle part**. Elle vit maintenant en SQL a cote de la donnee, comme la
  fraicheur, avec un test qui verifie que les deux implementations partagent leurs
  constantes et jugent pareil aux bornes. Mesure sur les vraies donnees : **1,21 %**
  de prix atypiques, pile dans la fourchette de la reconnaissance.
  **Les agregats journaliers.** La spec prevoyait un instantane de grain station x
  carburant x jour : chiffre fait avant d'ecrire, **plus de 400 millions de lignes**
  pour un budget de 6,5 Go, et redondant avec `fact_prix`. Remplace par un agregat sur
  les prix **en vigueur**, en format long. Spec corrigee.
  **Les facteurs d'emission de l'ADEME**, historises sans jamais de mise a jour en
  place. Verifies par requete reelle avant d'ecrire une ligne : les noms de champs
  portent les accents, ce que la spec n'avait pas vu, et une requete sans accents
  renvoie une page d'erreur au lieu d'une erreur JSON.
  **L'amorcage de l'historique**, en streaming. Charge en vrai pour les deux eres
  d'unite : 2007 (862 528 prix, mediane gazole 1,075 EUR) et 2022 (5 043 144 prix,
  1,862 EUR). Rejoue : zero ligne. Partition DEFAULT vide sur 27 partitions. Un prix
  relu en heure de Paris redonne exactement l'horodatage du XML.
  **Trois defauts trouves en faisant tourner** : le controle des prix atypiques
  depassait 25 secondes, la reference departementale etant reevaluee par paquets de
  lignes (materialisee : 0,84 s) ; le parseur d'archives attrapait `KeyError` la ou la
  normalisation leve `CarburantInconnu`, donc un nom de carburant inattendu aurait
  fait planter tout l'amorcage ; et deux de mes tests etaient faux.
  **Volumetrie corrigee par mesure** : 120,2 octets par ligne contre 102 estimes, soit
  **7,7 Go** pour l'historique complet et **50 minutes** de chargement.
  Nouvelles commandes : `etl qualite`, `etl refresh`, `etl facteurs`, `etl backfill`.

- **2026-11-25 — Le Jalon 1 est en ligne.**
  <https://carburant.144-24-195-97.sslip.io>, en HTTPS, certificat Let's Encrypt
  obtenu au premier essai. Le deploiement part d'un runner GitHub, installe Docker
  sur le VPS, ecrit sa configuration, tire les images multi-architecture depuis GHCR,
  applique les migrations, demarre la pile et **rejoue le parcours Playwright contre
  le site en ligne**.
  **La machine est enfin connue** : Ampere aarch64, Oracle Linux 9.8, 10 Go de RAM,
  4 Go de swap deja present, 17 Go de disque libre. PostGIS est desormais la meme
  image partout (imresamu/postgis:18-3.6-alpine, multi-architecture) : ecrire du SQL
  contre 3.7 pour le deployer sur 3.6 etait un piege gratuit.
  **Sept obstacles, tous diagnostiques par les journaux du deploiement :**
  `/opt` appartient a root et `opc` ne pouvait pas y creer le repertoire ;
  **`ssh-keyscan` faisait bannir le runner par fail2ban** -- il ouvre une connexion
  par type de cle et les referme avant authentification, ce que fail2ban compte comme
  un echec, et les connexions suivantes etaient jetees sans reponse, ce qui ressemblait
  a une panne reseau (confirme en lisant la liste des bannis : une adresse Azure y
  figurait) ; **nginx occupait le port 80** -- le VPS n'etait pas vide, le projet de
  mini-jeux de Baptiste y tournait, decision prise avec lui de passer a Caddy seul ;
  le certificat n'etait pas encore delivre quand l'essai depuis l'exterieur est passe.
  **Verifie sur le site en ligne**, pas en local : 20 stations reelles autour du Prado,
  triees par prix, chacune avec sa date ; aucune erreur de console ; `/v1/sante` au
  vert ; et surtout les prix **bougent** -- 1,975 € « il y a 2 heures » la ou la veille
  on lisait 1,990 € « il y a 23 heures ». Le collecteur tourne tout seul toutes les
  quinze minutes.
  Captures du site en ligne dans `docs/captures/production/`.
  Reste a Baptiste le seul test que personne d'autre ne peut faire : son iPhone.

- **2026-11-24 — Jalon 1, etape 6 : le deploiement.** Pile de production autonome
  (`compose.prod.yaml`) avec Caddy en reverse proxy, workflow GitHub Actions qui
  construit et publie les images **multi-architecture** sur GHCR puis deploie par ssh
  depuis le runner, `make deploy` pour declencher la chose a la main, et collecte
  planifiee par supercronic.
  **Images verifiees publiees en amd64 et arm64** pour les trois briques : le VPS ne
  construira rien, quelle que soit son architecture (toujours inconnue a ce jour).
  **La pile de production a reellement tourne ici** : cinq conteneurs sains, accueil
  rendu cote serveur avec les 9 825 stations, parcours complet joue dans un navigateur
  a travers Caddy — adresse ambigue, cinq candidats, 20 stations avec prix et dates —
  et **aucune erreur de console**.
  **Trois defauts trouves par cet essai, aucun par relecture :**
  la politique de securite du contenu posee par Caddy bloquait les deux scripts en
  ligne de Nuxt (carte d'import, configuration publique) ; la page s'affichait
  parfaitement, rendue cote serveur, mais plus rien ne repondait. Le site pose
  desormais sa propre politique avec un **nonce par requete**, et un test Playwright
  surveille la console pendant tout le parcours, parce qu'aucune autre assertion ne
  voit la difference tant qu'on ne touche pas aux boutons.
  La meme politique laissait `/docs` en page blanche : Swagger UI charge son script,
  sa feuille et sa police depuis jsdelivr. L'API a donc sa propre politique.
  Enfin, une variable d'environnement vide produisait un `email` sans argument dans le
  Caddyfile et Caddy redemarrait en boucle : le defaut d'un placeholder ne s'applique
  qu'a une variable **absente**, pas vide. La directive est supprimee.
  Deux details au passage : le schema OpenAPI est servi sous `/v1/openapi.json` et non
  a la racine, et Nitro envoyait deja le `Cache-Control` des fichiers versionnes, que
  Caddy redeclarait en double.
  Nouveau job CI « Infra » : coherence des deux piles **a partir du seul
  `.env.example`**, Caddyfile valide et bien formate, table cron valide, empreinte de
  supercronic identique a celle du Dockerfile. CI verte sur 4 jobs ; workflow de
  deploiement vert, avec l'etape de deploiement **sautee sans echec** faute de secrets.

- **2026-11-24 — Jalon 1, etape 5 : l'accueil mobile, verifie.** La page avait ete
  ecrite la veille sans jamais tourner. Elle tourne maintenant contre la vraie API et
  la vraie base : « le Prado, Marseille » est annonce comme ambigu, les cinq candidats
  sont proposes, et le choix d'un candidat sort 20 stations reelles triees par prix,
  chacune avec sa date et sa distance.
  Test obligatoire de `CLAUDE.md` ecrit : le parcours « chercher depuis un telephone »,
  sur iPhone SE, Pixel 7 et bureau. Il verifie aussi que le tri est croissant, que
  chaque station porte une date, que changer de carburant relance vraiment la recherche
  (les prix changent), qu'aucune cible n'est sous 44 px, qu'il n'y a pas de defilement
  horizontal et que la geolocalisation n'est demandee qu'au clic.
  **Quatre defauts trouves par ces tests, aucun par relecture :** l'accueil debordait
  de 191 px a 375 px de large (regle UA `min-inline-size: min-content` sur les
  `fieldset`, qui l'emporte sur `overflow-x: auto`) ; les boutons radio masques,
  absolus sans bloc conteneur local, se positionnaient par rapport a la barre collante
  et ajoutaient 125 px de defilement horizontal ; `overflow-y: auto` sur le `main`
  rognait le filet terracotta de la station la moins chere ; les liens de paire de la
  planche de style mesuraient 42,75 px de large pour 44 exiges.
  **Trois corrections nees de la relecture des captures :** le titre des resultats ne
  porte plus que le lieu (« Gazole pres de Avenue du prado » n'est pas du francais, et
  aucune elision ne tient sur des libelles de geocodeur) ; le site n'affiche plus le
  champ technique `raison` (« le meilleur candidat ne marque que 0,608 ») ; la croix
  d'effacement native du champ, bleue dans Chrome, est redessinee a l'encre du site, et
  une recherche sans resultat le dit au lieu de rester muette.
  **Deux pieges d'outillage corriges :** Playwright reutilisait un serveur lance avant
  le build et capturait donc un site perime ; et il reclame le Chromium 1255 quand
  l'image fournit le 1243, ce qui faisait echouer tous les tests.
  33 captures, 35,3 Mo compresses a 7,3 Mo. `make check` : 281 tests verts.

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
