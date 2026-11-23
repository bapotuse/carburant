# Avancement

## Prochaine action
Session de cadrage (voir le message de démarrage) : reconnaissance, anti-patterns, propositions design, plan du Jalon 0, questions à Baptiste.

## En attente de Baptiste
(rien pour l'instant)

## Jalons
Chaque jalon se termine par : critère de sortie vérifié, bilan à Baptiste, mise à jour de comprendre-le-projet.md.

### J0 — Socle
- [ ] Arborescence du monorepo, workspace uv, pnpm pour `web/`
- [ ] Docker Compose avec PostGIS ; Makefile (`up`, `down`, `etl`, `test`, `check`, `captures`, `deploy`)
- [ ] Lint, formatage, typage, pre-commit
- [ ] CI GitHub Actions (lint + tests)
- [ ] README squelette avec schéma d'architecture Mermaid ; squelettes de decisions.md, comprendre-le-projet.md, a-verifier.md
- [ ] [VALIDATION] Planche de style : page statique rendant 2 ou 3 paires typographiques × palette claire et sombre × prix façon totem × jauge × ticket de caisse, captures mobiles (valeurs d'exemple étiquetées comme telles)

Sortie : `make up && make check` vert sur une machine propre ; CI verte sur GitHub.

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
(une ligne datée par session : ce qui a été fait, ce qui a été vérifié)
