-- `marts.prix_courant` traversait vingt ans d'historique pour TOUTES les stations.
--
-- Mesure sur le VPS le 28/11/2026, apres l'amorcage : `/v1/anecdotes/du-jour`
-- repondait en **28,7 secondes** et depassait son delai dix-neuf fois sur vingt. Les
-- controles qualite de l'ETL, eux, mettaient **huit minutes et demie** la ou ils
-- prenaient moins d'une seconde avant l'amorcage. Meme cause pour les deux : cette
-- vue fait un `DISTINCT ON` par station sur `marts.fact_prix`, sans borne de date,
-- soit 64 millions de lignes sur 242 partitions pour 9 828 stations.
--
-- La correction est la meme que pour les recherches (migration 011) : une borne basse
-- sur `maj`, qui permet l'elagage des partitions.
--
-- **Ce que la vue signifie change, et il faut le dire.** Elle rendait « le dernier
-- prix connu de chaque station », perimes compris. Elle rend maintenant « le dernier
-- prix **encore exploitable** » : une station dont le dernier prix d'un carburant a
-- plus de trente et un jours n'y figure plus pour ce carburant, au lieu d'y figurer
-- avec `fraicheur = 'perime'`.
--
-- Pourquoi c'est sans consequence pour ses consommateurs : les quatre ecartent deja
-- les prix perimes.
--
--   * `marts.reference_departementale` : `fraicheur IN ('frais','recent')`
--   * `marts.classement_enseigne`      : `fraicheur <> 'perime'`
--   * controle `prix_suspects`         : `fraicheur IN ('frais','recent')`
--   * anecdote `ecart_du_jour`         : `fraicheur IN ('frais','recent')`
--
-- Le seul a changer de portee est le controle `prix_dans_les_bornes`, qui verifiait
-- aussi les prix perimes. Il ne verifie plus que les prix exploitables, et c'est
-- acceptable : les bornes sont appliquees **a l'entree**, a la frontiere
-- raw -> staging, ou un prix hors bornes est rejete et compte dans `staging.rejet`.
-- Un prix hors bornes ne peut donc pas entrer en base par la collecte ni par
-- l'amorcage. Le controle est un filet, pas la regle.
--
-- Les prix perimes restent visibles la ou ils doivent l'etre : sur la fiche d'une
-- station (`/v1/stations/{id}`), qui a sa propre requete et ne cache rien.

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
          -- La borne qui rend cette vue utilisable sur vingt ans d'historique.
          AND p.maj >= marts.horizon_prix_exploitable()
        ORDER BY p.carburant, p.maj DESC
  ) f
  LEFT JOIN marts.rupture r
         ON r.station_id = s.id AND r.carburant = f.carburant
 WHERE s.active;

COMMENT ON VIEW marts.prix_courant IS
  'Dernier prix ENCORE EXPLOITABLE par station et par carburant (moins de 31 jours), avec sa classe de fraicheur et l etat de rupture. Les prix perimes sont visibles sur la fiche d une station, qui a sa propre requete.';
