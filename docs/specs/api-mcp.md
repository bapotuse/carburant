# Spécification — API et serveur MCP

## API (FastAPI)
- FastAPI, pydantic v2, SQLAlchemy Core + psycopg 3, pas d'ORM. Préfixe `/v1`.
- OpenAPI soignée : résumé et description pour chaque route, exemples réels, unités dans les noms de champs (`prix_eur_l`, `distance_km`, `co2_kg`). Le front et le MCP consomment ce contrat : le client TypeScript du front est généré depuis l'OpenAPI, et la CI échoue s'il n'est pas à jour.
- Pagination, validation, erreurs au format `application/problem+json`.
- Cache : durée alignée sur la collecte pour les prix, 24 h ou plus pour le géocodage, 1 h pour les tendances ; en-têtes `Cache-Control` et `ETag`.
- Rate limiting par IP ; CORS limité aux origines du site.
- `/v1/sante` : base joignable, âge de la dernière collecte réussie, 503 au-delà du seuil. `/v1/meta` : dernière collecte, nombre de stations, versions des sources.
- Objectif : p95 < 300 ms sur le VPS pour `/stations/proches` (index GiST et `ST_DWithin` sur geography).

### Endpoints (noms indicatifs)
- `GET /v1/stations/proches?lat&lon&rayon_km&carburant&tri=prix|distance|cout_reel`
- `GET /v1/stations/meilleure?lat&lon&autonomie_km&carburant&litres&conso_l_100km`
- `GET /v1/stations/{id}` et `GET /v1/stations/{id}/historique?carburant&depuis`
- `GET /v1/tendances?departement&carburant&periode`
- `GET /v1/empreinte?carburant&litres` et `GET /v1/empreinte/comparaison?litres`
- `GET /v1/geocode?q=` : proxy Géoplateforme avec cache, limité à la France, renvoie plusieurs candidats avec leur score
- `GET /v1/anecdotes/du-jour`

## Logique « meilleure station » (cœur du projet)
Entrées : position P, carburant c, autonomie A (km), litres L, consommation C (L/100 km), marge m = 0,8, facteur de détour s (distance routière ≈ distance géodésique × s ; valeur initiale 1,3, à justifier ou calibrer, et à documenter). Valeurs par défaut de L et C à proposer et à documenter.
1. d = distance géodésique(P, station) × s, ou la distance routière réelle pour les N meilleurs candidats si le service d'itinéraire est branché.
2. Atteignable si d ≤ A × m.
3. Exclure : rupture sur c, prix périmé, prix suspect, station inactive.
4. cout_reel = prix × L + prix × (2 × d × C / 100). Hypothèse documentée : aller-retour depuis P, carburant du trajet valorisé au prix de la station.
5. Trier par cout_reel ; renvoyer les N premiers avec le détail (prix, distance, coût du détour, fraîcheur).
6. economie = cout_reel(station atteignable la plus proche) − cout_reel(meilleure station).
7. Cas limites explicites et testés : aucune station atteignable (renvoyer la plus proche avec un avertissement clair), autonomie nulle ou négative, carburant absent de la zone, position hors de France, égalités, station la plus proche qui est aussi la meilleure (économie nulle).

Tests : fonction de coût pure (tests unitaires) ; propriétés avec hypothesis (le coût croît avec la distance, l'économie est toujours ≥ 0, une station hors autonomie n'est jamais recommandée) ; intégration PostGIS sur un jeu de stations synthétiques autour du Prado.

## Serveur MCP
- Le dossier `mcp/` ne doit jamais être lui-même importable (layout `src/`, pas de `__init__.py` à sa racine, nom d'import du type `carburant_mcp`) : sinon il masquerait le SDK `mcp`.
- Package Python dans `mcp/`, installable avec `uvx` : depuis PyPI si Baptiste crée un compte, sinon `uvx --from "git+https://github.com/<compte>/<depot>#subdirectory=mcp" <nom>`. Nom à proposer : court, explicite, libre sur PyPI (vérifie).
- SDK officiel `mcp`, ligne 2.x : stable depuis fin juillet 2026, il suit la spécification MCP du 2026-07-28, et la classe serveur de haut niveau a été renommée par rapport à FastMCP v1. Lis la documentation et le guide de migration de la version installée ; n'écris pas de code v1 de mémoire.
- Le serveur appelle uniquement l'API publique (URL configurable par variable d'environnement, production par défaut), jamais la base : n'importe qui peut l'installer.
- Deux transports :
  - stdio, pour l'installation locale ;
  - Streamable HTTP déployé sur le VPS (par exemple `https://<domaine>/mcp`), sans état, sans authentification, avec rate limiting, pour qu'un recruteur l'ajoute comme connecteur distant sans rien installer.
- Tools, avec des descriptions écrites pour un modèle : quand utiliser ce tool plutôt qu'un autre, format et exemples des arguments, unités, contenu de la réponse, limites.
  - `trouver_station_moins_chere(lieu: str, carburant: str, rayon_km: float = 5)`
  - `meilleure_station_avec_autonomie(lieu: str, carburant: str, autonomie_km: float, litres: float | None = None)`
  - `prix_station(station: str)` : identifiant ou adresse
  - `tendance_prix(zone: str, carburant: str, periode: str)` : département (nom ou code) ou ville
  - `empreinte_carbone_plein(carburant: str, litres: float)`
  - `comparer_carburants(lieu: str)`
- `carburant` accepte les synonymes courants (« diesel », « sans plomb 95 », « E10 », « super ») et les normalise ; une valeur inconnue renvoie une erreur qui liste les valeurs acceptées.
- `lieu` est du texte libre géocodé via `/v1/geocode`. Si le résultat est ambigu (score faible ou plusieurs lieux plausibles : « le Prado » en est un exemple), renvoie les candidats au lieu de deviner.
- Réponses concises : sortie structurée (schéma) et texte court. Pour chaque station : adresse, ville, prix au format français, distance, date de mise à jour, avertissement si le prix date de plus de 24 h, lien vers la fiche sur le site, lien d'itinéraire. Tools annotés en lecture seule.
- Erreurs exploitables par le modèle, par exemple « lieu introuvable : précise la ville ou le code postal ».
- Tests : session client en mémoire du SDK avec API simulée (respx) ; smoke test avec MCP Inspector en mode CLI contre l'API locale ; un test de bout en bout contre la production après déploiement.
- README : configuration pour Claude Desktop, Claude Code (`claude mcp add`), les autres clients MCP et le connecteur distant ; 5 conversations d'exemple tirées de vrais appels, dont « Je suis au Prado à Marseille, où est l'essence la moins chère ? » et « J'ai 20 km d'autonomie, où faire le plein ? ».
