-- Un horizon de recherche, pour que les recherches ne traversent plus vingt ans.
--
-- Le probleme, mesure le 28/11/2026 sur le plan d'execution reel : la recherche de
-- stations proches fait, **pour chaque station candidate**, un parcours d'index sur
-- **chacune** des partitions de `marts.fact_prix` -- 242 apres l'amorcage de
-- l'historique -- puis trie l'ensemble pour garder le prix le plus recent. Soit
-- plusieurs milliers de parcours d'index et vingt ans de changements de prix tries,
-- pour repondre une question qui ne porte que sur le prix du jour.
--
-- La correction est une borne basse sur `maj`, qui permet l'elagage des partitions.
-- Verifie : `Subplans Removed: 12` sur 16 partitions locales, 3 partitions retenues.
--
-- **Pourquoi cette borne ne change aucun resultat.** Les recherches ecartent deja
-- les prix perimes (plus de trente jours) : une station dont le dernier prix est
-- perime n'apparait pas, avec ou sans la borne. Mettre la borne un jour **avant** le
-- seuil de peremption garantit donc que tout ce qu'elle exclut aurait de toute facon
-- ete ecarte. Le jour de marge n'est pas de la superstition : l'audit du 26/11 a
-- trouve une fenetre a trente et un jours la ou elle devait en faire trente, et une
-- borne trop juste rendrait le resultat dependant de l'heure de la requete.
--
-- Le seuil de peremption devient une fonction, pour que la classe de fraicheur et
-- l'horizon de recherche ne puissent plus deriver l'un de l'autre.

CREATE OR REPLACE FUNCTION marts.jours_avant_peremption() RETURNS integer
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT 30 $$;

COMMENT ON FUNCTION marts.jours_avant_peremption() IS
  'Au-dela de ce nombre de jours, un prix est perime. Seuil mesure, voir docs/reconnaissance.md section 1.9. Source unique : classe_fraicheur et horizon_prix_exploitable le lisent ici.';

-- `classe_fraicheur` lit desormais le seuil ici plutot que de le repeter. Le reste de
-- la fonction est inchange, bornes comprises.
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
        WHEN maj IS NULL                            THEN NULL
        WHEN reference - maj <= interval '48 hours' THEN 'frais'
        WHEN reference - maj <= interval '7 days'   THEN 'recent'
        WHEN reference - maj <= marts.jours_avant_peremption() * interval '1 day'
                                                    THEN 'ancien'
        ELSE                                             'perime'
    END
$$;

-- `STABLE` et non `IMMUTABLE` : la valeur depend de `now()`. C'est ce qu'il faut pour
-- que PostgreSQL elague les partitions a l'initialisation du plan.
CREATE OR REPLACE FUNCTION marts.horizon_prix_exploitable(
    reference timestamptz DEFAULT now()
) RETURNS timestamptz
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
    SELECT reference - (marts.jours_avant_peremption() + 1) * interval '1 day'
$$;

COMMENT ON FUNCTION marts.horizon_prix_exploitable(timestamptz) IS
  'Borne basse de maj pour les recherches : un jour avant la peremption, donc tout prix anterieur aurait de toute facon ete ecarte. Permet l elagage des partitions.';
