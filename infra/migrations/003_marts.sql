-- 003 : le modele d'exposition.
--
-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`).
--
-- Trois tables et une regle qui gouverne tout le reste : le grain de `fact_prix` est
-- **un changement de prix**, pas une collecte. Stocker chaque collecte ferait environ
-- 9 800 stations x 6 carburants x 96 collectes par jour, soit 5,66 millions de lignes
-- quotidiennes presque toutes identiques. Les vrais changements se comptent en
-- dizaines de milliers : 5 297 799 sur l'annee 2025, soit environ 14 500 par jour.
-- Un rapport de 390 (docs/reconnaissance.md section 2.4).

-- ---------------------------------------------------------------- dim_carburant
CREATE TABLE IF NOT EXISTS marts.dim_carburant (
    code          text PRIMARY KEY,
    libelle       text NOT NULL,
    nom_flux      text NOT NULL,
    token_couleur text NOT NULL,
    -- Forme de l'etiquette europeenne EN 16942 : cercle pour les essences, carre pour
    -- le gazole, losange pour le GPL. La couleur n'est jamais seule porteuse du sens.
    forme         text NOT NULL CHECK (forme IN ('cercle', 'carre', 'losange')),
    borne_min     numeric(5,3) NOT NULL,
    borne_max     numeric(5,3) NOT NULL,
    ordre         smallint NOT NULL,
    CONSTRAINT bornes_coherentes CHECK (borne_min < borne_max)
);

COMMENT ON TABLE marts.dim_carburant IS
  'Les six carburants publies par le flux. Alimentee depuis carburant_etl.carburants, qui reste la source de verite.';

-- ---------------------------------------------------------------- dim_station
CREATE TABLE IF NOT EXISTS marts.dim_station (
    id               bigint PRIMARY KEY,
    -- `geography` et non `geometry` : les distances sortent en metres sur
    -- l'ellipsoide, sans se demander dans quelle projection on se trouve.
    geom             geography(Point, 4326) NOT NULL,
    cp               text,
    adresse          text,
    ville            text,
    departement      text,
    code_departement text,
    region           text,
    code_region      text,
    -- Derive de `pop` : 'A' vaut autoroute, 'R' vaut route. 4,4 % des stations.
    autoroute        boolean NOT NULL DEFAULT false,
    horaires         jsonb,
    services         text[] NOT NULL DEFAULT '{}',
    -- Nullables, avec leur provenance : le flux officiel ne contient ni nom ni
    -- enseigne. Le rapprochement OpenStreetMap arrive au Jalon 2.
    enseigne         text,
    enseigne_source  text,
    enseigne_score   real CHECK (enseigne_score IS NULL OR enseigne_score BETWEEN 0 AND 1),
    premiere_vue     timestamptz NOT NULL,
    derniere_vue     timestamptz NOT NULL,
    -- Une station absente du flux n'est jamais supprimee : elle devient inactive.
    active           boolean NOT NULL DEFAULT true,
    collectes_manquees smallint NOT NULL DEFAULT 0
);

COMMENT ON TABLE marts.dim_station IS
  'Une ligne par station, mise a jour en place (SCD de type 1). Une station disparue devient inactive, jamais supprimee.';
COMMENT ON COLUMN marts.dim_station.enseigne IS
  'Absent du flux officiel. Rapproche d OpenStreetMap au Jalon 2, avec sa source et son score.';

-- L'index qui fait tout le travail de `/v1/stations/proches`.
CREATE INDEX IF NOT EXISTS dim_station_geom_gix ON marts.dim_station USING GIST (geom);
CREATE INDEX IF NOT EXISTS dim_station_departement_idx
    ON marts.dim_station (code_departement) WHERE active;

-- ---------------------------------------------------------------- fact_prix
CREATE TABLE IF NOT EXISTS marts.fact_prix (
    station_id        bigint       NOT NULL REFERENCES marts.dim_station (id),
    carburant         text         NOT NULL REFERENCES marts.dim_carburant (code),
    prix              numeric(5,3) NOT NULL,
    -- Instant du changement de prix. C'est la cle de partition, et elle doit figurer
    -- dans la contrainte d'unicite : c'est pourquoi on partitionne sur `maj` et non
    -- sur la date de collecte.
    maj               timestamptz  NOT NULL,
    -- Collecte qui a vu ce prix pour la premiere fois, et derniere fois qu'on l'a
    -- revu. Relancer l'ETL ne touche que `derniere_observation`.
    premiere_collecte bigint       NOT NULL,
    derniere_observation timestamptz NOT NULL,
    PRIMARY KEY (station_id, carburant, maj)
) PARTITION BY RANGE (maj);

COMMENT ON TABLE marts.fact_prix IS
  'Grain : un changement de prix. Partitionnee par mois sur maj, bornes calculees en UTC.';
COMMENT ON COLUMN marts.fact_prix.derniere_observation IS
  'Derniere collecte ou ce prix etait encore affiche. Seule colonne touchee par une relance.';

-- Partition DEFAULT : elle doit rester VIDE. Une ligne ici signale que l'ETL n'a pas
-- cree la partition du mois voulu -- ou que les bornes ont ete ecrites sans fuseau,
-- auquel cas la premiere heure de chaque mois en heure de Paris y tombe
-- (3 612 lignes constatees sur l'archive 2025, docs/reconnaissance.md section 2.5).
CREATE TABLE IF NOT EXISTS marts.fact_prix_defaut PARTITION OF marts.fact_prix DEFAULT;

-- Pas d'index supplementaire sur (station_id, carburant, maj DESC) : mesure, il
-- coute 205 Mo par an et n'apporte rien, la cle primaire servant deja ces recherches
-- dans les deux sens (docs/reconnaissance.md section 2.4).

-- ---------------------------------------------------------------- ruptures
CREATE TABLE IF NOT EXISTS marts.rupture (
    station_id   bigint NOT NULL REFERENCES marts.dim_station (id),
    carburant    text   NOT NULL REFERENCES marts.dim_carburant (code),
    type         text   NOT NULL CHECK (type IN ('temporaire', 'definitive')),
    debut        timestamptz,
    derniere_vue timestamptz NOT NULL,
    PRIMARY KEY (station_id, carburant)
);

COMMENT ON TABLE marts.rupture IS
  'Etat courant des ruptures. Une rupture definitive dit « cette station ne vend pas ce carburant » : ce n est pas une panne.';

-- ---------------------------------------------------------------- garnissage
-- Les six carburants. Garder la liste ici evite une jointure applicative, mais la
-- source de verite reste `carburant_etl.carburants` : un test verifie que les deux
-- ne divergent pas.
INSERT INTO marts.dim_carburant
    (code, libelle, nom_flux, token_couleur, forme, borne_min, borne_max, ordre)
VALUES
    ('gazole', 'Gazole',   'Gazole', 'carburant-gazole', 'carre',   0.80, 3.50, 1),
    ('sp95',   'SP95',     'SP95',   'carburant-sp95',   'cercle',  0.80, 3.50, 2),
    ('e10',    'SP95-E10', 'E10',    'carburant-e10',    'cercle',  0.80, 3.50, 3),
    ('sp98',   'SP98',     'SP98',   'carburant-sp98',   'cercle',  0.80, 3.50, 4),
    ('e85',    'E85',      'E85',    'carburant-e85',    'cercle',  0.35, 1.60, 5),
    ('gplc',   'GPLc',     'GPLc',   'carburant-gplc',   'losange', 0.35, 2.00, 6)
ON CONFLICT (code) DO UPDATE SET
    libelle       = EXCLUDED.libelle,
    nom_flux      = EXCLUDED.nom_flux,
    token_couleur = EXCLUDED.token_couleur,
    forme         = EXCLUDED.forme,
    borne_min     = EXCLUDED.borne_min,
    borne_max     = EXCLUDED.borne_max,
    ordre         = EXCLUDED.ordre;
