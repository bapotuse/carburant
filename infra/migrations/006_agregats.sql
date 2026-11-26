-- 006 : la reference departementale materialisee, et les agregats journaliers.
--
-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`).
--
-- ## Pourquoi materialiser la reference
--
-- La vue `marts.reference_departementale` de la migration 005 recalculait la
-- mediane et la MAD de chaque departement a chaque interrogation. Mesure du
-- 26/11/2026 : 1,55 s pour la vue seule, et **plus de 25 secondes** des qu'on la
-- joignait aux prix pour signaler les suspects -- le planificateur la reevaluait
-- par paquets de lignes. Materialisee, la jointure devient immediate.
--
-- Elle est rafraichie a la fin de chaque chargement (`etl refresh`). Entre deux
-- rafraichissements, les medianes ont au plus quinze minutes : amplement assez
-- stable pour juger qu'un prix est atypique.
--
-- ## Pourquoi un agregat par jour et non un instantane par station
--
-- La specification prevoyait `snapshot_prix_jour`, de grain station x carburant x
-- jour. Chiffre fait : 9 825 stations x 6 carburants x 7 000 jours d'historique =
-- **plus de 400 millions de lignes**, pour un projet dont le budget total est de
-- 6,5 Go. Et cette table serait redondante avec `fact_prix`, qui garde deja chaque
-- changement et raconte donc l'histoire d'une station mieux qu'un echantillonnage
-- quotidien.
--
-- Ce que la specification voulait vraiment eviter est ailleurs : moyenner les seuls
-- prix *modifies* un jour donne biaise les moyennes vers les stations qui changent
-- souvent leurs prix. On l'evite en agregeant les prix **en vigueur** ce jour-la,
-- directement, sans passer par une table intermediaire geante.
--
-- Format long plutot qu'une colonne par dimension : une seule table, une seule cle,
-- et on ajoutera le classement par enseigne sans migration de schema.

-- ------------------------------------------------------- reference materialisee
DROP VIEW IF EXISTS marts.prix_courant_qualifie;
DROP VIEW IF EXISTS marts.reference_departementale;

CREATE MATERIALIZED VIEW IF NOT EXISTS marts.reference_departementale AS
WITH utilisables AS (
    SELECT s.code_departement, c.carburant, c.prix
      FROM marts.prix_courant c
      JOIN marts.dim_station s ON s.id = c.station_id
     WHERE c.fraicheur IN ('frais', 'recent')
       AND c.rupture_type IS NULL
       AND s.code_departement IS NOT NULL
),
medianes AS (
    SELECT code_departement, carburant,
           count(*)::integer AS stations,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)::numeric AS mediane
      FROM utilisables
     GROUP BY 1, 2
)
SELECT m.code_departement,
       m.carburant,
       m.stations,
       m.mediane,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(u.prix - m.mediane))::numeric AS mad
  FROM medianes m
  JOIN utilisables u
    ON u.code_departement = m.code_departement AND u.carburant = m.carburant
 GROUP BY 1, 2, 3, 4;

COMMENT ON MATERIALIZED VIEW marts.reference_departementale IS
  'Mediane et MAD par departement et carburant, sur les prix frais ou recents hors rupture. Rafraichie a chaque chargement.';

-- Index unique : indispensable pour `REFRESH ... CONCURRENTLY`, qui evite de
-- bloquer les lectures de l'API pendant le rafraichissement.
CREATE UNIQUE INDEX IF NOT EXISTS reference_departementale_cle
    ON marts.reference_departementale (code_departement, carburant);

-- ------------------------------------------------------- la vue servie
CREATE OR REPLACE VIEW marts.prix_courant_qualifie AS
SELECT c.station_id,
       c.carburant,
       c.prix,
       c.maj,
       c.fraicheur,
       c.rupture_type,
       c.rupture_debut,
       s.code_departement,
       s.autoroute,
       r.mediane      AS mediane_departement,
       r.mad          AS mad_departement,
       r.stations     AS stations_departement,
       marts.est_suspect(c.prix, r.mediane, r.mad, r.stations) AS suspect,
       marts.ecart_mad(c.prix, r.mediane, r.mad)               AS ecart_mad
  FROM marts.prix_courant c
  JOIN marts.dim_station s ON s.id = c.station_id
  LEFT JOIN marts.reference_departementale r
         ON r.code_departement = s.code_departement AND r.carburant = c.carburant;

COMMENT ON VIEW marts.prix_courant_qualifie IS
  'Le dernier prix de chaque station, avec sa fraicheur, son etat de rupture et son signalement de prix atypique.';

-- ------------------------------------------------------- agregats journaliers
CREATE TABLE IF NOT EXISTS marts.agregat_prix_jour (
    jour        date NOT NULL,
    carburant   text NOT NULL REFERENCES marts.dim_carburant (code),
    -- Sur quoi porte l'agregat. Format long : une ligne par decoupage, et on
    -- ajoutera 'enseigne' au Jalon 2 sans toucher au schema.
    dimension   text NOT NULL CHECK (dimension IN ('france', 'departement', 'reseau')),
    -- La valeur de ce decoupage : '' pour la France entiere, un code de departement,
    -- ou 'autoroute' / 'route'.
    valeur      text NOT NULL,
    stations    integer NOT NULL,
    -- Les prix suspects et les prix anciens ou perimes sont exclus du calcul, mais
    -- on garde leur nombre : un agregat doit pouvoir dire sur quoi il ne porte pas.
    exclus      integer NOT NULL DEFAULT 0,
    prix_min    numeric(5,3) NOT NULL,
    prix_median numeric(5,3) NOT NULL,
    prix_moyen  numeric(5,3) NOT NULL,
    prix_max    numeric(5,3) NOT NULL,
    calcule_le  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (jour, carburant, dimension, valeur),
    CONSTRAINT agregat_coherent CHECK (prix_min <= prix_median AND prix_median <= prix_max)
);

COMMENT ON TABLE marts.agregat_prix_jour IS
  'Prix agreges par jour, calcules sur les prix EN VIGUEUR ce jour-la et non sur les seuls prix modifies ce jour-la.';
COMMENT ON COLUMN marts.agregat_prix_jour.exclus IS
  'Prix ecartes du calcul : atypiques, anciens, perimes ou en rupture. Un agregat doit dire sur quoi il ne porte pas.';

CREATE INDEX IF NOT EXISTS agregat_prix_jour_serie
    ON marts.agregat_prix_jour (carburant, dimension, valeur, jour DESC);

-- ------------------------------------------------------- etat des ruptures
CREATE OR REPLACE VIEW marts.rupture_courante AS
SELECT r.carburant,
       r.type,
       count(*)::integer AS stations,
       min(r.debut)      AS plus_ancienne,
       max(r.derniere_vue) AS derniere_vue
  FROM marts.rupture r
  JOIN marts.dim_station s ON s.id = r.station_id AND s.active
 GROUP BY 1, 2;

COMMENT ON VIEW marts.rupture_courante IS
  'Combien de stations actives sont en rupture, par carburant et par type.';
