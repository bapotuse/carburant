# Carburant

Projet portfolio de Baptiste (étudiant à 42 Marseille) destiné à des recruteurs en data engineering et en développement web. Trois briques :
1. un pipeline ETL qui collecte les prix des carburants en France, les nettoie, les historise et les enrichit de l'empreinte carbone ;
2. un site web public, pensé d'abord pour le smartphone, chaleureux et épuré, qui ne doit pas avoir l'air généré par une IA ;
3. un serveur MCP Python qui permet à n'importe qui de demander à son assistant « Où est l'essence la moins chère près de moi ? Je suis au Prado à Marseille », « J'ai 20 km d'autonomie, où faire le plein ? », « Le gazole a-t-il baissé ce mois-ci dans les Bouches-du-Rhône ? ».

**Tu réalises tout** : code, configuration, tests, documentation, déploiement. Tu lances toi-même les commandes, lis les erreurs et corriges jusqu'à ce que ça marche. Baptiste ne code pas : il valide les choix de goût, fait les actions sur ses comptes et présentera le projet en entretien. Ne lui demande jamais d'écrire, de modifier ou de copier du code. Baptiste a un iPhone : c'est l'appareil de test réel.

## Stack imposée
- PostgreSQL ≥ 16 + PostGIS.
- ETL : Python ≥ 3.12 (dernière version stable supportée par toutes les dépendances), httpx, pydantic, SQL brut ou SQLAlchemy Core, pas d'ORM. Planification cron d'abord, structure prête pour Prefect.
- API : FastAPI, OpenAPI documentée.
- Front : Nuxt (dernière stable), Vue 3 Composition API, TypeScript, MapLibre GL, Three.js via TresJS si compatible.
- MCP : SDK MCP Python officiel ; le serveur appelle l'API publique, jamais la base.
- Infra : Docker Compose, GitHub Actions, VPS Oracle Cloud derrière Caddy.
- Monorepo : `etl/`, `api/`, `web/`, `mcp/`, `infra/`, `docs/`.

## Où est quoi

@docs/avancement.md

| Fichier | Contenu | Quand le lire |
|---|---|---|
| docs/avancement.md | jalons, cases, prochaine action, attentes, journal | toujours (importé ci-dessus) |
| docs/specs/donnees.md | sources, modèle, règles ETL, qualité | avant tout travail dans etl/ ou en SQL |
| docs/reconnaissance.md | constats sur les sources réelles (champs, volumes, distributions) | avant de modifier l'ETL ou les seuils |
| docs/specs/api-mcp.md | endpoints, logique « meilleure station », MCP | avant api/ ou mcp/ |
| docs/specs/web.md | pages, mobile, direction artistique, 3D, anecdotes, perf | avant web/ |
| docs/specs/infra.md | Docker, VPS, CI, sauvegardes, monitoring | avant infra/ ou la CI |
| docs/decisions.md | une ligne par décision : date, choix, raison, alternative écartée | à compléter à chaque décision |
| docs/anti-patterns-ia.md | grille de contrôle du design | avant chaque page ou composant |
| docs/comprendre-le-projet.md | documentation pédagogique pour l'entretien | à mettre à jour en fin de jalon |
| docs/a-verifier.md | faits et chiffres non confirmés | dès qu'un doute apparaît |

Si la réalité contredit une spec (champ absent, API modifiée, version incompatible), adapte-toi, mets la spec à jour et note-le dans decisions.md. Ne t'écarte jamais d'une spec en silence.

## Boucle de travail
- Début de session ou après une compaction : relis docs/avancement.md et `git log --oneline -20`, puis reprends à « Prochaine action ».
- Pour chaque tâche : lire la spec concernée → implémenter la plus petite tranche utile → vérifier (section suivante) → commit → mettre à jour avancement.md (case cochée, prochaine action, une ligne datée dans le journal).
- Sous-agents : utilise-les pour les recherches documentaires volumineuses et pour les revues indépendantes (`revue-design`, `revue-donnees` dans `.claude/agents/`). Ils protègent ton contexte, et une revue faite par quelqu'un qui n'a pas produit le travail est plus fiable.

## Terminé = observé
Une tâche n'est terminée que si tu as constaté toi-même :
- `make check` vert (lint, formatage, typage, tests) ;
- le service démarre avec `make up` et répond (curl, navigateur) ;
- pour l'interface : captures Playwright produites par `make captures` dans `docs/captures/<jalon>/` (iPhone SE 375×667, Pixel 7, bureau 1440×900, thèmes clair et sombre), que tu as ouvertes et comparées à docs/anti-patterns-ia.md ; captures compressées, seule la dernière série de chaque jalon est conservée ;
- pour les données : chargées depuis la vraie source, comptes vérifiés.

Ce que tu n'as pas pu vérifier, dis-le explicitement. Ne présente jamais comme fonctionnel quelque chose que tu n'as pas fait tourner.

## Quand t'arrêter pour Baptiste
Seulement dans ces trois cas. Avant de t'arrêter, termine tout ce qui ne dépend pas de sa réponse, puis regroupe tout dans un seul message.
1. **Validations de goût**, marquées [VALIDATION] dans avancement.md : planche de style (typographie, palette, prix façon totem), maquettes mobiles de l'accueil et de la carte, objets 3D, nom du projet et du package MCP. Donne les chemins des captures mobiles, 2 ou 3 options, ta recommandation en premier.
2. **Actions sur ses comptes** : GitHub, VPS Oracle Cloud, domaine et DNS, secrets, PyPI, service d'alerte. Instructions pour un non-codeur : où cliquer, quoi copier-coller exactement, comment vérifier que c'est bon, ce que tu feras ensuite. Ne lui fais jamais coller un secret dans la conversation quand il peut le saisir directement dans un fichier `.env` ou dans les secrets GitHub.
3. **Opération destructive en production** : suppression de données ou de volumes, migration irréversible, commande destructive sur le VPS.

Format des questions : numérotées, options lettrées, recommandation en premier, comportement par défaut si Baptiste répond « ok ». Pour tout le reste, décide seul : l'option la plus simple et la plus robuste, une ligne dans decisions.md.

## Bilan de fin de jalon
En français simple et court : ce qui marche ; comment le voir (une URL ou une seule commande) ; chemins des captures ; ce qui reste ; ce dont tu as besoin de Baptiste.

## Vérité des données et des faits
- Aucun chiffre, facteur d'émission, fait historique ou anecdote inventé. Chaque fait éditorial porte sa source (URL, titre, date de consultation) stockée à côté. Au moindre doute, ne publie pas : ajoute-le à docs/a-verifier.md.
- Les API et bibliothèques ont pu changer depuis tes données d'entraînement. Vérifie toute API externe par une vraie requête avant de coder contre elle. Pour les bibliothèques qui évoluent vite (Nuxt, SDK MCP, TresJS, MapLibre, PWA), lis la documentation de la version installée plutôt que ta mémoire.
- Pas de données factices en dehors des tests. Un prix affiché l'est toujours avec sa date de mise à jour.

## Garde-fous
- Ne jamais affaiblir, supprimer ou désactiver un test pour le faire passer, ni coder en dur une sortie attendue. Si un test est faux, corrige-le et explique pourquoi dans le message de commit.
- Pas de `--no-verify`, pas de force-push sur `main`, pas de réécriture d'un historique déjà poussé.
- Aucun secret dans le dépôt : `.env.example` + variables d'environnement, `.env` ignoré par git. Pas de données brutes ni de dumps commités.
- Ne lis jamais de clé privée (`~/.ssh/id_*`) ; tu peux vérifier qu'elle existe.
- Production : sauvegarde avant toute migration ; demande avant toute opération destructive.
- Toute nouvelle dépendance doit se justifier, surtout côté front (poids JS). Note les dépendances structurantes dans decisions.md.

## Priorités en cas de conflit
1. Exactitude des données affichées (prix, fraîcheur, CO2)
2. Trouver une station depuis un téléphone, d'une main, vite
3. Performance mobile et accessibilité
4. Code lisible et explicable en entretien
5. Finition visuelle et détails « univers carburant »
6. 3D

Quand la 3D ou les animations menacent les points 2 ou 3, ce sont elles qu'on allège.

## Conventions
- Français pour l'interface, la documentation, les commits et les noms métier (station, carburant, prix, y compris routes d'API et tools MCP), sans accents dans les identifiants ; anglais pour le vocabulaire technique usuel.
- Commits : Conventional Commits avec description en français, par exemple `feat(etl): historise les prix par changement`. Un commit par étape logique. Push dès que le dépôt distant existe.
- Python : uv (workspace), ruff (lint et formatage), mypy strict, pytest. Front : pnpm, eslint, prettier, vue-tsc, Vitest, Playwright. pre-commit pour les deux.
- Formats français : `Intl` en `fr-FR` côté front, helpers testés côté Python (réponses MCP) : `1,879 €`, `23 nov.`, espaces insécables.
- Tests obligatoires : nettoyage des données, coût réel, calcul CO2, recherche géographique, parcours « chercher depuis un téléphone » (Playwright).

## docs/comprendre-le-projet.md
Pour que Baptiste présente le projet sans l'avoir codé : architecture expliquée simplement (schéma Mermaid), rôle de chaque brique, concepts clés expliqués en 3 phrases chacun (ETL, modèle en couches raw/staging/marts, partitionnement, idempotence, PostGIS, API REST et OpenAPI, SSR, PWA, Three.js, MCP), choix techniques et compromis, chiffres réels du projet (volumes, durées d'exécution, scores Lighthouse), et 20 questions probables d'un recruteur avec des éléments de réponse. Mis à jour à chaque fin de jalon.

## Commandes
À compléter au Jalon 0, puis à tenir à jour : `make up`, `make down`, `make etl`, `make test`, `make check`, `make captures`, `make deploy`.
