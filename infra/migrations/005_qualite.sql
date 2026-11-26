-- 005 : la regle des prix suspects, et la vue qui la porte.
--
-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`).
--
-- Comme `marts.classe_fraicheur`, la regle vit a cote de la donnee : elle est lue
-- par l'API (pour signaler un prix atypique), par l'ETL (controles qualite) et par
-- les vues agregees (qui excluent les suspects). Trois lecteurs, une seule
-- definition.
--
-- Ce que la regle dit, et ce qu'elle ne dit pas. Un prix suspect n'est PAS un prix
-- faux : les prix signales sont le plus souvent de vrais prix eleves -- L'Ile-d'Yeu,
-- Val-d'Isere, Saint-Tropez, Cauterets. Ils sont donc **conserves et affiches**,
-- simplement exclus des classements et des moyennes. Ce qui est faux, ce sont les
-- prix hors bornes absolues, et ceux-la sont rejetes avant d'entrer en base.
--
-- Les trois constantes viennent de mesures (docs/reconnaissance.md section 1.10),
-- pas d'intuition :
--
--   plancher de MAD  0,05 EUR  sans lui la regle signale 8 a 19 % des prix, parce
--                              que la MAD departementale tombe a 0,0005 EUR la ou
--                              beaucoup de stations affichent le meme prix
--   facteur          5         avec le plancher : 0,4 a 2,5 % de prix signales
--   stations minimum 5         on ne juge pas un prix sur trois voisins
--
-- Un test verifie que ces trois valeurs sont identiques a celles de
-- `carburant_etl.transformation.aberrants`, et qu'aux bornes les deux repondent
-- pareil.

-- --------------------------------------------------------------- les constantes
-- En fonctions plutot qu'en litteraux disperses : un seul endroit a changer, et
-- elles sont interrogeables depuis les tests.
CREATE OR REPLACE FUNCTION marts.plancher_mad() RETURNS numeric
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT 0.05::numeric $$;

CREATE OR REPLACE FUNCTION marts.facteur_mad() RETURNS numeric
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT 5::numeric $$;

CREATE OR REPLACE FUNCTION marts.min_stations_departement() RETURNS integer
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT 5 $$;

-- --------------------------------------------------------------- la regle
CREATE OR REPLACE FUNCTION marts.est_suspect(
    prix numeric,
    mediane numeric,
    mad numeric,
    stations integer
) RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN mediane IS NULL OR stations IS NULL THEN false
        WHEN stations < marts.min_stations_departement() THEN false
        ELSE abs(prix - mediane)
             > marts.facteur_mad() * greatest(mad, marts.plancher_mad())
    END
$$;

COMMENT ON FUNCTION marts.est_suspect(numeric, numeric, numeric, integer) IS
  'Un prix s ecarte-t-il trop de la mediane de son departement ? Suspect = conserve et affiche, exclu des classements.';

CREATE OR REPLACE FUNCTION marts.ecart_mad(
    prix numeric,
    mediane numeric,
    mad numeric
) RETURNS numeric
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT CASE WHEN mediane IS NULL THEN NULL
                ELSE abs(prix - mediane) / greatest(mad, marts.plancher_mad())
           END
$$;

COMMENT ON FUNCTION marts.ecart_mad(numeric, numeric, numeric) IS
  'Ecart a la mediane departementale, en nombre de MAD plancherees. Stocke a cote du signalement pour qu il soit verifiable.';

-- --------------------------------------------------------------- la reference
-- Mediane et dispersion par departement et par carburant, calculees sur les seuls
-- prix qui ont le droit de faire reference : frais ou recents, hors rupture. Un
-- prix de trois semaines ne doit pas tirer la mediane du jour.
CREATE OR REPLACE VIEW marts.reference_departementale AS
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
       -- MAD : la mediane des ecarts absolus a la mediane. Non plancheree ici,
       -- c'est la vraie dispersion observee ; le plancher s'applique dans la regle.
       percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(u.prix - m.mediane))::numeric AS mad
  FROM medianes m
  JOIN utilisables u
    ON u.code_departement = m.code_departement AND u.carburant = m.carburant
 GROUP BY 1, 2, 3, 4;

COMMENT ON VIEW marts.reference_departementale IS
  'Mediane et MAD par departement et carburant, sur les prix frais ou recents hors rupture.';

-- --------------------------------------------------------------- la vue servie
CREATE OR REPLACE VIEW marts.prix_courant_qualifie AS
SELECT c.station_id,
       c.carburant,
       c.prix,
       c.maj,
       c.fraicheur,
       c.rupture_type,
       c.rupture_debut,
       s.code_departement,
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
