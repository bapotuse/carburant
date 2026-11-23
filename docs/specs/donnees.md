# Spécification — données et ETL

Faits vérifiés le 23/11/2026. Revérifie chaque source par une vraie requête avant de coder.

## Sources

### Prix et stations
Jeu « Prix des carburants en France – Flux instantané – v2 » (DGCCRF / ministères économiques, Licence Ouverte 2.0).
- API Explore v2.1 : `https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/`. Pour le jeu complet, utilise `exports/` (parquet, csv ou json) ; `records/` est paginé et plafonné, inadapté à un chargement complet.
- Source amont : `https://donnees.roulez-eco.fr/opendata/instantane_ruptures` (zip XML), mise à jour toutes les 10 min ; data.economie la moissonne environ toutes les 15 min. Garde-la comme source de repli : data.economie a déjà connu des indisponibilités.
- Collecte toutes les 15 min : plus souvent, on ne récupère rien de neuf.
- Carburants publiés : Gazole, SP95, SP95-E10, SP98, E85, GPLc. Rien d'autre.
- Format large : une ligne par station, des colonnes par carburant (prix, date de mise à jour, rupture), horaires, services, `pop` (route ou autoroute), géométrie.
- Le flux officiel ne contient probablement ni nom ni enseigne de station (à confirmer pendant la reconnaissance). Ne les invente pas et ne scrape pas prix-carburants.gouv.fr. Piste par défaut pour les enseignes : rapprochement spatial PostGIS avec OpenStreetMap (`amenity=fuel`, tags `brand` et `name`, licence ODbL, attribution obligatoire), avec un score de correspondance stocké et un taux de couverture mesuré et affiché. Sans enseigne, une station s'affiche par son adresse et sa ville.

### Historique
Le flux ne donne que l'état courant : on historise nous-mêmes. Pour amorcer l'historique :
- archives annuelles `https://donnees.roulez-eco.fr/opendata/annee/<AAAA>` (zip XML, depuis 2007 ; environ 400 Mo zippés et 4,3 Go de XML au total) ;
- flux quotidien J-1 `https://donnees.roulez-eco.fr/opendata/jour`.

Le schéma XML diffère du flux v2 et les unités peuvent varier selon les années (coordonnées multipliées, prix en millièmes d'euro) : vérifie sur échantillon et teste la conversion. Parse en streaming (`iterparse`), jamais 4 Go en mémoire. Périmètre à valider en cadrage ; défaut : détail complet sur les dernières années selon le volume mesuré, agrégats quotidiens département × carburant pour les années antérieures.

### Empreinte carbone
Base Carbone® / Base Empreinte® de l'ADEME (Licence Etalab 2.0), API sur le portail open data de l'ADEME. Facteurs en kgCO2e par litre, périmètre combustion + amont, France continentale.
- Un même élément peut couvrir plusieurs carburants (par exemple un seul pour les supercarburants SP95, E10 et SP98) : documente le mapping carburant → élément.
- Ordres de grandeur pour contrôle de cohérence uniquement, jamais comme valeurs : essence ≈ 2,7 ; gazole ≈ 3,1 ; E85 ≈ 1,1 ; GPL ≈ 1,9 kgCO2e/L. Un écart de plus de 20 % : vérifie l'unité (par kg ? par MJ ?) avant toute chose.

### Géocodage
`api-adresse.data.gouv.fr` a été décommissionnée fin janvier 2026. Utilise le géocodage de la Géoplateforme IGN : `https://data.geopf.fr/geocodage/search` (et l'autocomplétion Géoplateforme si utile). Respecte les limites de débit documentées : cache côté API, anti-rebond côté front.

### Distance routière (optionnel, tardif)
Service d'itinéraire de la Géoplateforme IGN, ou OSRM (le serveur de démonstration public n'est pas prévu pour la production : lis ses conditions). Uniquement sur les meilleurs candidats.

## Modèle (PostgreSQL + PostGIS)
Schémas `raw`, `staging`, `marts`, `meta`. Migrations versionnées (outil simple, choix noté dans decisions.md).

### raw
Fichier brut compressé sur disque, horodaté. Pas de nouveau fichier si son sha256 est identique au précédent. Rétention configurable (défaut 14 jours). Table `raw.collecte` : id, source, url, début, fin, octets, sha256, statut, nombre de lignes. Sert à rejouer une transformation sans retélécharger.

### staging
Flux aplati au format long, une ligne par station × carburant : prix, date de mise à jour, rupture (type, début), id de collecte. Chargement par `COPY`.

### marts
- `dim_station` : id officiel, `geom geography(Point,4326)` avec index GiST, adresse, code postal, ville, département (champ du flux s'il existe, sinon jointure spatiale avec les contours départementaux ; attention à la Corse 2A/2B et aux DROM), autoroute (booléen dérivé de `pop`), horaires (jsonb normalisé), services (text[]), enseigne et nom (nullables, avec source et score), première vue, dernière vue, active. SCD de type 1.
- `dim_carburant` : code normalisé (`gazole`, `sp95`, `e10`, `sp98`, `e85`, `gplc`), libellé, clé du token couleur, lien vers le facteur d'émission courant.
- `ref_facteur_emission` : carburant, identifiant ADEME de l'élément, libellé exact, valeur, unité, périmètre, version de la base, URL, date de récupération, valide_depuis. Jamais de mise à jour en place : une nouvelle version donne une nouvelle ligne.
- `fact_prix` : **grain = un changement de prix**, unicité sur `(station_id, carburant, maj)`. Colonnes : prix `numeric(5,3)`, maj `timestamptz`, collecte de première observation, date de dernière observation.
  - Partitionnement mensuel sur `maj` : la clé de partition doit figurer dans la contrainte d'unicité, c'est pourquoi on partitionne sur `maj` et non sur la date de collecte.
  - Partitions du mois courant et du suivant créées à chaque exécution ; partition DEFAULT pour les dates hors plage, qui doit rester vide (alerte sinon).
  - Chargement en `INSERT … ON CONFLICT DO UPDATE` sur la date de dernière observation : relancer une exécution ne crée aucun doublon.
  - Pourquoi ce grain : stocker chaque collecte ferait environ 10 000 stations × 6 carburants × 96 collectes par jour, soit près de 6 millions de lignes quotidiennes presque toutes répétées ; les vrais changements se comptent en dizaines de milliers par jour. Mesure le chiffre réel et écris-le dans comprendre-le-projet.md.
- `snapshot_prix_jour` : station × carburant × jour → prix **en vigueur** ce jour-là (dernier changement avant la fin du jour, non périmé). Toutes les tendances partent de cette table. Raison : moyenner seulement les prix modifiés un jour donné biaise les moyennes vers les stations qui changent souvent leurs prix.
- Vues (matérialisées si nécessaire, rafraîchies après chaque chargement) : prix moyen et médian par jour × département × carburant ; autoroute vs route ; stations les moins chères par zone ; classement des enseignes (seulement si la couverture est suffisante, taux affiché) ; état courant des ruptures.

### meta
`execution_etl` : début, fin, statut, lignes par étape, avertissements, erreur. Source de la fraîcheur affichée sur le site et des alertes.

## Règles de transformation (chacune testée)
- Une seule table de normalisation des codes carburant.
- Fuseau horaire : vérifie si les dates du flux sont en heure locale ou en UTC ; stocke en `timestamptz`, affiche en Europe/Paris. Teste le passage à l'heure d'hiver et d'été.
- Prix aberrants : bornes **par carburant** (E85 et GPLc coûtent bien moins cher que le gazole) dérivées de la distribution réelle, plus une règle relative (écart à la médiane départementale du jour, en nombre de MAD). Hors bornes absolues : rejeté et compté. Suspect : conservé, signalé, exclu des classements.
- Fraîcheur, selon les seuils validés en cadrage. Proposition à affiner avec les données : frais < 24 h ; ancien de 1 à 7 jours, affiché avec avertissement ; périmé au-delà, exclu des recherches mais visible sur la fiche.
- Ruptures : un carburant en rupture est exclu des recherches et affiché comme tel sur la fiche.
- Déduplication : un même `(station, carburant, maj)` donne une seule ligne ; même `maj` avec un prix différent : on garde la dernière observation et on journalise.
- Station absente du flux : `active = false` après N collectes manquées, jamais supprimée.

## Contrôles qualité
Exécutés à chaque run ; un échec met le run en erreur et déclenche l'alerte.
- Nombre de stations à ±10 % de la moyenne des 7 derniers jours.
- Prix dans les bornes ; part de prix suspects sous un seuil.
- Coordonnées dans les emprises de la France métropolitaine et des DROM.
- Unicité du grain ; partition DEFAULT vide.
- Fraîcheur de la source : la date de mise à jour la plus récente a moins de 2 h.

Écrits en SQL, exécutés par l'ETL, couverts par pytest.

## Orchestration
- Une CLI : `etl run`, `etl backfill --annee AAAA`, `etl refresh`, `etl qualite`. Chaque étape (extract, transform, load, qualité) est une fonction idempotente : passer à Prefect plus tard consistera à envelopper ces fonctions, sans réécriture.
- Planification dans le conteneur etl (supercronic ou équivalent, logs sur stdout). Verrou `pg_advisory_lock` contre les exécutions concurrentes.
- httpx : timeout explicite, retries avec backoff exponentiel, User-Agent qui identifie le projet et l'URL du dépôt.
- Validation pydantic à la frontière raw → staging, erreurs comptées par champ.

## dbt
En fin de Jalon 2, propose dans le bilan la migration de la couche de transformation vers dbt-postgres : apports (lignage, tests déclaratifs, documentation générée), coût, recommandation. Ne migre qu'après accord.
