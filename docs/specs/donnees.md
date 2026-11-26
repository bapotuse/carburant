# Spécification — données et ETL

Faits vérifiés le 23/11/2026. Revérifie chaque source par une vraie requête avant de coder.

> **Mise à jour du 23/11/2026 après la reconnaissance.** Les constats réels sont dans
> `docs/reconnaissance.md`, qui fait foi pour les seuils et les volumes. Les passages corrigés
> ci-dessous portent la marque **[corrigé 23/11/2026]**. Les décisions correspondantes sont dans
> `docs/decisions.md`.

## Sources

### Prix et stations
Jeu « Prix des carburants en France – Flux instantané – v2 » (DGCCRF / ministères économiques, Licence Ouverte 2.0).
- API Explore v2.1 : `https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/`. Pour le jeu complet, utilise `exports/` (parquet, csv ou json) ; `records/` est paginé et plafonné, inadapté à un chargement complet.
- Source amont : `https://donnees.roulez-eco.fr/opendata/instantane_ruptures` (zip XML), mise à jour toutes les 10 min ; data.economie la moissonne environ toutes les 15 min. Garde-la comme source de repli : data.economie a déjà connu des indisponibilités.
- Collecte toutes les 15 min : plus souvent, on ne récupère rien de neuf.
- Carburants publiés : Gazole, SP95, SP95-E10, SP98, E85, GPLc. Rien d'autre.
- Format large : une ligne par station, des colonnes par carburant (prix, date de mise à jour, rupture), horaires, services, `pop` (route ou autoroute), géométrie.
- **[corrigé 23/11/2026]** Confirmé : le flux officiel ne contient **ni nom ni enseigne** de station — aucun des 47 champs.
- **[corrigé 23/11/2026]** Le flux expose en revanche `departement`, `code_departement`, `region` et `code_region`, renseignés pour 9 822 des 9 826 stations. **Aucune jointure spatiale n'est nécessaire pour le département.**
- **[corrigé 23/11/2026]** Les champs `latitude` et `longitude` du flux v2 sont du **texte en degrés × 100 000** (format PTV non converti). Le champ `geom` (`geo_point_2d`) est en degrés décimaux corrects, cohérence vérifiée sur les 9 826 stations : **utiliser `geom`**.
- **[corrigé 23/11/2026]** **Aucune station en DROM** dans le flux (0 code en 97x/98x). La Corse est présente en `2A`/`2B`. Les archives annuelles, elles, contiennent des DROM et des coordonnées aberrantes.
- **[corrigé 23/11/2026]** L'API répond en gzip/brotli : un client qui ne négocie pas l'encodage reçoit des octets illisibles. Ne les invente pas et ne scrape pas prix-carburants.gouv.fr. Piste par défaut pour les enseignes : rapprochement spatial PostGIS avec OpenStreetMap (`amenity=fuel`, tags `brand` et `name`, licence ODbL, attribution obligatoire), avec un score de correspondance stocké et un taux de couverture mesuré et affiché. Sans enseigne, une station s'affiche par son adresse et sa ville.

### Historique
Le flux ne donne que l'état courant : on historise nous-mêmes. Pour amorcer l'historique :
- archives annuelles `https://donnees.roulez-eco.fr/opendata/annee/<AAAA>` (zip XML, depuis 2007 ; **[corrigé 23/11/2026]** 439 Mo zippés mesurés et **≈ 5,4 Go** de XML décompressé, pas 4,3 Go) ;
- flux quotidien J-1 `https://donnees.roulez-eco.fr/opendata/jour`.

**[corrigé 23/11/2026]** Le schéma XML diffère du flux v2 **et change selon l'année** (mesuré) :

| Aspect | 2007 → 2013 | 2014 | 2016 → 2017 | 2018 → 2021 | 2022 → 2026 |
|---|---|---|---|---|---|
| Unité des prix | millièmes | millièmes | millièmes | millièmes | **euros** |
| Horaires | `<ouverture>` | `<ouverture>` | `<ouverture>` | `<horaires>` | `<horaires>` |
| Format de `maj` | espace + microsecondes | espace | `T` | `T` | `T` |

- Conversion retenue, valable sur les deux ères : **`si valeur > 20 alors valeur / 1000`**.
- **Les deux formats de `maj` coexistent dans un même fichier** (2025 : 5 297 800 en `T`, 96 en espace). Le parseur accepte les deux, avec ou sans microsecondes.
- Encodage **ISO-8859-1** déclaré (instantané comme archives) : décoder en `latin-1`.
- Coordonnées : ×100 000 mais **non entières** (3 539 valeurs décimales en 2025) et **sales** (70 stations hors emprise, jusqu'à 62,6° de latitude). Filtrer sur l'emprise et compter les rejets.
- ≈ 4 658 `<prix>` malformés (sans `nom`, `maj` ni `valeur`) par archive annuelle : comptés et rejetés.
- Un élément `<fermeture type debut fin>` existe dans les archives, absent du flux instantané.
- Parse en streaming (`iterparse`), jamais 5 Go en mémoire.

**Périmètre retenu : historique complet 2007 → aujourd'hui, en détail, sans agrégats dégradés.**
Mesuré : ≈ 64 M de lignes ≈ **6,5 Go** en base, chargeables en moins de 30 minutes. Le volume ne
justifie pas de dégrader les années anciennes.

### Empreinte carbone
**[corrigé 23/11/2026]** Base Carbone® de l'ADEME (Licence Ouverte). Le portail a **migré
d'Opendatasoft vers Data Fair** : l'ancienne API Explore v2.1 répond **HTTP 410**. Bonne base :

```
https://data.ademe.fr/data-fair/api/v1/datasets/base-carboner
```

18 616 lignes, `updatedAt` 2026-06-30. `/lines` accepte `qs` (Lucene), `size`, `select`, `after`.
**Filtrer sur `Type_Ligne = "Elément"`** : les lignes `Type_Ligne = "Poste"` portent la
décomposition amont / combustion et feraient compter les facteurs en double. L'unité s'écrit
`kgCO2e/litre`. Facteurs par litre, périmètre combustion + amont, France continentale.

Mapping retenu (tous « Valide générique », France continentale) :

| Carburant | Identifiant | Libellé exact | Valeur | Combustion | Amont |
|---|---|---|---|---|---|
| gazole | **25775** | Gazole routier — B7 | 3,1 | 2,49 | 0,609 |
| sp95 | **25763** | Essence — Supercarburant sans plomb (95, 95-E10, 98) | 2,69 | 2,20 | 0,491 |
| sp98 | **25763** | Essence — Supercarburant sans plomb (95, 95-E10, 98) | 2,69 | 2,20 | 0,491 |
| e10 | **13988** | Essence — E10 | 2,69 | 2,19 | 0,502 |
| e85 | **25766** | Essence — E85 | 1,11 | 0,366 | 0,743 |
| gplc | **14031** | GPL pour véhicule routier | 1,86 | 1,60 | 0,257 |

Pas de champ « version de la base » dans l'API : on stocke `updatedAt` du jeu,
`Date_de_modification` et `Période_de_validité` de l'élément.
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
  - **[corrigé 23/11/2026] Les bornes de partition doivent être calculées en UTC**, et l'amorçage doit créer la partition du **mois précédant** le premier mois de données. Mesuré : avec des bornes écrites sans fuseau, 3 612 lignes de l'archive 2025 tombent dans la partition DEFAULT — ce sont les prix du 1er janvier entre 00h00 et 00h58 heure de Paris, soit le 31 décembre en UTC.
  - **[corrigé 23/11/2026] Ne pas créer d'index `(station_id, carburant, maj DESC)`** : mesuré, il coûte 205 Mo par an (2,5 Go sur l'historique complet) et n'apporte rien, la clé primaire `(station_id, carburant, maj)` servant déjà ces recherches dans les deux sens.
  - **[corrigé 24/11/2026]** Les partitions créées à chaque exécution couvrent **la plage réelle des dates présentes**, plus le mois courant et le suivant — et non le seul mois courant comme prévu initialement. `maj` est la date du dernier *changement* de prix : elle remonte souvent à plus d'un an. Mesuré sur le vrai flux : les changements s'étalent de juillet 2025 à novembre 2026, soit **15 partitions**. S'en tenir à deux mois aurait mis plus de mille lignes dans la partition DEFAULT.
  - Partition DEFAULT pour les dates hors plage, qui doit rester vide (alerte sinon). Vérifié : 0 ligne après chargement du flux réel.
  - Chargement en `INSERT … ON CONFLICT DO UPDATE` sur la date de dernière observation : relancer une exécution ne crée aucun doublon.
  - Pourquoi ce grain : stocker chaque collecte ferait environ 10 000 stations × 6 carburants × 96 collectes par jour, soit près de 6 millions de lignes quotidiennes presque toutes répétées.
    **[corrigé 23/11/2026] Chiffre réel mesuré** sur l'archive 2025 : **5 297 799 changements de prix sur l'année, soit ≈ 14 500 par jour** — contre ≈ 5,66 millions de lignes par jour en stockant chaque collecte, **un rapport de 390**. Le grain unique est quasi parfait dans la source : **1 doublon exact sur 5,3 millions**. Volume mesuré en base : **307 Mo de données + 232 Mo d'index par an**, soit ≈ 102 Mo par million de lignes ; `COPY` de 5,3 M de lignes en **14 s**.
- ~~`snapshot_prix_jour` : station × carburant × jour~~ **[corrigé 26/11/2026]
  Remplacé par `marts.agregat_prix_jour`.** Chiffre fait : un instantané de grain
  station × carburant × jour sur l'historique complet ferait 9 825 × 6 × 7 000 jours,
  soit **plus de 400 millions de lignes**, pour un projet dont le budget total est de
  6,5 Go. Il serait de surcroît redondant avec `fact_prix`, qui garde chaque
  changement et raconte donc l'histoire d'une station mieux qu'un échantillonnage
  quotidien.
  Le biais que cette table devait éviter — moyenner les seuls prix *modifiés* un jour
  donné favorise les stations qui changent souvent leurs prix — est évité en
  agrégeant directement les prix **en vigueur** ce jour-là, sans table intermédiaire.
  Grain retenu : `(jour, carburant, dimension, valeur)` en format long, où `dimension`
  vaut `france`, `departement` ou `reseau`. Une seule table et une seule clé pour tous
  les découpages ; le classement par enseigne s'y ajoutera sans migration de schéma.
  Sont écartés du calcul **et comptés** : les prix périmés (plus de 30 jours), les
  carburants en rupture, et les prix atypiques au sens de `marts.est_suspect`.
- Vues (matérialisées si nécessaire, rafraîchies après chaque chargement) : prix moyen et médian par jour × département × carburant ; autoroute vs route ; stations les moins chères par zone ; classement des enseignes (seulement si la couverture est suffisante, taux affiché) ; état courant des ruptures.

### meta
`execution_etl` : début, fin, statut, lignes par étape, avertissements, erreur. Source de la fraîcheur affichée sur le site et des alertes.

## Règles de transformation (chacune testée)
- Une seule table de normalisation des codes carburant.
- **[corrigé 23/11/2026] Fuseau horaire : tranché.** Les dates du flux sont en **heure locale Europe/Paris**, servies par data.economie avec un suffixe **`+00:00` mensonger**. Preuve décisive : sur les 5,3 M d'horodatages de 2025, les profils horaires de janvier (UTC+1) et de juillet (UTC+2) se superposent (r = 0,9987 à décalage nul, 0,18 à −1 h) ; de plus 181 dates du flux sont « dans le futur » si on les lit en UTC. Détail dans `docs/reconnaissance.md` § 1.4.
  → **Parser en ignorant le suffixe, localiser en `Europe/Paris` (`zoneinfo`), stocker en `timestamptz`, afficher en Europe/Paris.** Tester le passage à l'heure d'hiver et d'été. Un contrôle qualité vérifie `max(maj) <= now()` à chaque exécution : si la source passe un jour réellement en UTC, l'alerte part.
- **[corrigé 23/11/2026] Prix aberrants.** Bornes absolues **par carburant**, dérivées de la distribution réelle : essences et gazole **[0,80 ; 3,50]**, E85 **[0,35 ; 1,60]**, GPLc **[0,35 ; 2,00]**. Hors bornes : rejeté et compté (elles attrapent exactement les 4 vraies erreurs de saisie observées le 23/11, trois E85 à 1,99 et un à 2,249).
  Règle relative : `suspect ⇔ |prix − médiane_départementale_du_jour| > 5 × max(MAD_dép, 0,05 €)`, avec au moins 5 stations dans le département.
  **Le plancher de 0,05 € est indispensable** : sans lui, la MAD départementale descend à 0,0005 € là où beaucoup de stations affichent le même prix, et la règle signale 8 à 19 % des prix. Avec le plancher : 0,4 à 2,5 %.
  Les prix ainsi signalés sont le plus souvent de **vrais** prix élevés (L'Île-d'Yeu, Val-d'Isère, Saint-Tropez) : **suspect = conservé, affiché, signalé, exclu des classements et des moyennes** — jamais rejeté.
- **[corrigé 23/11/2026] Fraîcheur, en 4 classes.** `maj` est la date du dernier **changement** de prix, pas du dernier contrôle : le seuil initial (périmé au-delà de 7 jours) écarterait **18 %** des prix et **40 %** du GPLc.

| Classe | Seuil | Couverture mesurée | Comportement |
|---|---|---|---|
| frais | ≤ 48 h | 39,5 % | affiché normalement |
| récent | 48 h → 7 j | 81,9 % cumulé | affiché, date discrète |
| ancien | 7 j → 30 j | 96,8 % cumulé | avertissement visible, **conservé** dans les recherches, exclu des classements et des moyennes |
| périmé | > 30 j | 3,2 % | exclu des recherches, visible sur la fiche avec sa date |

  Dans tous les cas, **la date de mise à jour est affichée** : jamais un prix nu.
- Ruptures : un carburant en rupture est exclu des recherches et affiché comme tel sur la fiche.
- Déduplication : un même `(station, carburant, maj)` donne une seule ligne ; même `maj` avec un prix différent : on garde la dernière observation et on journalise.
- Station absente du flux : `active = false` après N collectes manquées, jamais supprimée.

## Contrôles qualité
Exécutés à chaque run ; un échec met le run en erreur et déclenche l'alerte.
- Nombre de stations à ±10 % de la moyenne des 7 derniers jours.
- Prix dans les bornes ; part de prix suspects sous un seuil.
- **[corrigé 23/11/2026]** Coordonnées dans l'emprise **France métropolitaine + Corse** pour le flux instantané (aucune station en DROM n'y figure). L'amorçage des archives, lui, filtre sur la même emprise et **compte les rejets** (DROM historiques et aberrations : 70 stations hors emprise en 2025).
- Unicité du grain ; partition DEFAULT vide.
- Fraîcheur de la source : la date de mise à jour la plus récente a moins de 2 h.

Écrits en SQL, exécutés par l'ETL, couverts par pytest.

**[précisé 26/11/2026]** Chaque contrôle renvoie `(ok, mesure)`, la mesure étant une
phrase lisible dans un journal. Deux niveaux : **bloquant** (l'exécution est marquée
en échec et le processus sort en erreur) et **avertissement** (consigné, l'exécution
reste un succès). Sont des avertissements la fraîcheur de la source — elle peut
légitimement ne rien publier pendant deux heures — et la part de prix atypiques, qu'une
vague de hausses réelles fait monter sans que rien ne soit cassé.
**Un contrôle en échec ne rejette jamais les données chargées** : c'est l'exécution
qu'on marque, pas la donnée qu'on jette.
S'y ajoute `aucune_date_future`, le garde-fou du fuseau horaire décrit plus haut.

## Orchestration
- Une CLI : `etl run`, `etl backfill --annee AAAA`, `etl refresh`, `etl qualite`. Chaque étape (extract, transform, load, qualité) est une fonction idempotente : passer à Prefect plus tard consistera à envelopper ces fonctions, sans réécriture.
- Planification dans le conteneur etl (supercronic ou équivalent, logs sur stdout). Verrou `pg_advisory_lock` contre les exécutions concurrentes.
- httpx : timeout explicite, retries avec backoff exponentiel, User-Agent qui identifie le projet et l'URL du dépôt.
- Validation pydantic à la frontière raw → staging, erreurs comptées par champ.

## dbt
En fin de Jalon 2, propose dans le bilan la migration de la couche de transformation vers dbt-postgres : apports (lignage, tests déclaratifs, documentation générée), coût, recommandation. Ne migre qu'après accord.
