-- 010 : le classement des enseignes.
--
-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`).
--
-- La specification conditionnait ce classement a une couverture suffisante, et
-- demandait que le taux soit affiche. Mesure du 26/11/2026 sur le VPS :
-- **99,4 % des stations actives portent une enseigne** -- 9 761 rapprochees par
-- l'identifiant officiel d'OpenStreetMap, 8 par la geographie, 59 sans. La
-- condition est largement remplie.
--
-- **Le regroupement se fait sur `brand:wikidata`, pas sur le libelle.** Mesure sur
-- les 12 613 points OSM de France : les libelles eclatent une meme enseigne
-- -- TotalEnergies 1 209, Total 1 078, Total Access 405 -- la ou `Q154037` en compte
-- 2 674, soit leur somme. Un classement bati sur le libelle compterait Total trois
-- fois et le ferait passer derriere Intermarche a tort.
--
-- Les stations dont OSM ne donne pas d'identifiant Wikidata sont regroupees sur
-- leur libelle, faute de mieux, et le disent.

CREATE OR REPLACE VIEW marts.classement_enseigne AS
WITH stations AS (
    SELECT coalesce(s.enseigne_wikidata, 'libelle:' || s.enseigne) AS cle,
           s.enseigne_wikidata,
           s.enseigne,
           s.id,
           s.autoroute
      FROM marts.dim_station s
     WHERE s.active AND s.enseigne IS NOT NULL
),
regroupees AS (
    SELECT cle,
           enseigne_wikidata,
           -- Le libelle le plus frequent du groupe : « TotalEnergies » plutot que
           -- « Total Access » pour representer Q154037.
           mode() WITHIN GROUP (ORDER BY enseigne) AS enseigne,
           count(*)::integer                       AS stations,
           count(*) FILTER (WHERE autoroute)::integer AS stations_autoroute
      FROM stations
     GROUP BY cle, enseigne_wikidata
),
prix AS (
    SELECT s.cle, c.carburant,
           count(*)::integer AS prix_comptes,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY c.prix)::numeric(5,3) AS prix_median
      FROM stations s
      JOIN marts.prix_courant_qualifie c ON c.station_id = s.id
     -- Les memes exclusions que les agregats : un classement ne se fait pas sur des
     -- prix atypiques ni sur des carburants que la station ne vend pas.
     WHERE NOT c.suspect
       AND c.rupture_type IS NULL
       AND c.fraicheur <> 'perime'
     GROUP BY s.cle, c.carburant
)
SELECT r.enseigne,
       r.enseigne_wikidata,
       r.stations,
       r.stations_autoroute,
       p.carburant,
       p.prix_comptes,
       p.prix_median
  FROM regroupees r
  LEFT JOIN prix p ON p.cle = r.cle;

COMMENT ON VIEW marts.classement_enseigne IS
  'Prix median par enseigne et par carburant. Regroupe sur brand:wikidata : les libelles eclatent une meme enseigne. A n afficher qu accompagne du taux de couverture (marts.couverture_enseigne).';
