-- 004 : la classe de fraicheur d'un prix, definie une seule fois.
--
-- Ce fichier NE gere PAS sa transaction : c'est le lanceur de migrations qui
-- l'ouvre et la ferme (`carburant_etl.chargement.migrations`).
--
-- Pourquoi en SQL et pas en Python : la regle est lue par l'API (pour etiqueter
-- chaque prix) et par l'ETL (pour ses controles qualite). Ces deux paquets ne
-- dependent pas l'un de l'autre et ne doivent pas : le serveur MCP, lui, n'appelle
-- que l'API publique. Mettre la regle a cote de la donnee evite d'en avoir deux
-- versions qui derivent. Un test d'integration verifie que la fonction SQL et la
-- fonction Python `carburant_etl.transformation.fraicheur.classer` repondent la meme
-- chose aux bornes.
--
-- Les seuils viennent de mesures, pas d'intuition (docs/reconnaissance.md section
-- 1.9). `maj` est la date du dernier CHANGEMENT de prix, pas du dernier controle :
-- une station qui ne bouge pas ses prix pendant dix jours n'est pas fausse pour
-- autant. Le seuil initialement propose -- perime au-dela de 7 jours -- ecartait
-- 18 % des prix et 40 % du GPLc.
--
--   frais   <= 48 h        39,5 % des prix    affiche normalement
--   recent  <= 7 jours     81,9 % cumule      affiche, date discrete
--   ancien  <= 30 jours    96,8 % cumule      avertissement, hors classements
--   perime  > 30 jours      3,2 %             hors recherches, visible sur la fiche

CREATE OR REPLACE FUNCTION marts.classe_fraicheur(
    maj timestamptz,
    reference timestamptz DEFAULT now()
) RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT CASE
        -- Une maj dans le futur est traitee comme fraiche : c'est au controle
        -- qualite `max(maj) <= now()` de la signaler, pas a l'affichage.
        WHEN maj IS NULL                               THEN NULL
        WHEN reference - maj <= interval '48 hours'    THEN 'frais'
        WHEN reference - maj <= interval '7 days'      THEN 'recent'
        WHEN reference - maj <= interval '30 days'     THEN 'ancien'
        ELSE                                                'perime'
    END
$$;

COMMENT ON FUNCTION marts.classe_fraicheur(timestamptz, timestamptz) IS
  'Classe de fraicheur d un prix : frais, recent, ancien ou perime. Seuils mesures, voir docs/reconnaissance.md section 1.9.';

-- Le dernier prix connu de chaque station pour chaque carburant, avec sa fraicheur
-- et l etat de rupture. C'est la vue que l'API interroge : elle evite de repeter la
-- meme sous-requete `LATERAL` dans chaque endpoint.
CREATE OR REPLACE VIEW marts.prix_courant AS
SELECT s.id                AS station_id,
       f.carburant,
       f.prix,
       f.maj,
       marts.classe_fraicheur(f.maj) AS fraicheur,
       r.type              AS rupture_type,
       r.debut             AS rupture_debut
  FROM marts.dim_station s
  CROSS JOIN LATERAL (
       -- `DISTINCT ON (carburant)` : le DERNIER changement de prix de chaque
       -- carburant, pas tout l'historique. `fact_prix` garde chaque changement.
       SELECT DISTINCT ON (p.carburant) p.carburant, p.prix, p.maj
         FROM marts.fact_prix p
        WHERE p.station_id = s.id
        ORDER BY p.carburant, p.maj DESC
  ) f
  LEFT JOIN marts.rupture r
         ON r.station_id = s.id AND r.carburant = f.carburant
 WHERE s.active;

COMMENT ON VIEW marts.prix_courant IS
  'Dernier prix connu par station et par carburant, avec sa classe de fraicheur et l etat de rupture.';
