-- 009 : de quoi tracer d'ou vient une enseigne.
--
-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`).
--
-- `dim_station` portait deja `enseigne`, `enseigne_source` et `enseigne_score`. Il
-- manquait deux choses pour que le rapprochement soit verifiable et le classement
-- juste.
--
-- **L'identifiant Wikidata de la marque.** Les libelles eclatent une meme enseigne :
-- mesure du 26/11/2026 sur OSM, TotalEnergies 1 209, Total 1 078, Total Access 405,
-- la ou `brand:wikidata = Q154037` en compte 2 674 -- leur somme. Un classement bati
-- sur le libelle compterait Total trois fois.
--
-- **L'identifiant OSM de l'objet rapproche.** Sans lui, un rapprochement ne peut pas
-- etre reverifie : on saurait qu'une station s'appelle Avia sans pouvoir dire d'ou
-- cela sort. Avec lui, `https://www.openstreetmap.org/node/144574` tranche.

ALTER TABLE marts.dim_station
    ADD COLUMN IF NOT EXISTS enseigne_wikidata text,
    ADD COLUMN IF NOT EXISTS enseigne_osm      text,
    ADD COLUMN IF NOT EXISTS enseigne_vue_le   timestamptz;

COMMENT ON COLUMN marts.dim_station.enseigne_wikidata IS
  'Identifiant Wikidata de la marque (brand:wikidata). C est lui qui sert aux classements : les libelles eclatent une meme enseigne.';
COMMENT ON COLUMN marts.dim_station.enseigne_osm IS
  'Objet OpenStreetMap rapproche, par exemple node/144574. Rend le rapprochement reverifiable.';
COMMENT ON COLUMN marts.dim_station.enseigne_source IS
  'osm-reference quand OSM portait l identifiant officiel de la station (score 1,0), osm-spatial quand le rapprochement est geographique (score degrade selon la distance).';

CREATE INDEX IF NOT EXISTS dim_station_enseigne_wikidata
    ON marts.dim_station (enseigne_wikidata) WHERE enseigne_wikidata IS NOT NULL;

-- Combien de stations actives portent une enseigne, et d'ou elle vient. C'est le
-- taux que la specification demande de mesurer **et d'afficher** : un classement
-- d'enseignes sur une couverture inconnue ne vaut rien.
CREATE OR REPLACE VIEW marts.couverture_enseigne AS
SELECT coalesce(enseigne_source, 'aucune')      AS source,
       count(*)::integer                        AS stations,
       round(100.0 * count(*) / nullif(sum(count(*)) OVER (), 0), 1) AS part_pourcent,
       round(avg(enseigne_score)::numeric, 3)   AS score_moyen
  FROM marts.dim_station
 WHERE active
 GROUP BY 1;

COMMENT ON VIEW marts.couverture_enseigne IS
  'Part des stations actives portant une enseigne, par provenance du rapprochement.';
