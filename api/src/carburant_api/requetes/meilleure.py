"""Candidates au titre de « meilleure station ».

Le partage du travail est volontaire : **le SQL trouve les candidates, Python les
classe.** La fonction de coût est pure, testée par des propriétés sur des centaines
de combinaisons (`carburant_api.calcul.cout`) ; la réécrire en SQL en ferait une
seconde implémentation à garder d'accord avec la première. Le rayon étant borné par
l'autonomie, on parle de quelques centaines de lignes : les classer en Python ne
coûte rien.

Quatre exclusions, et chacune a sa raison :

- **rupture** : la station ne vend pas ce carburant aujourd'hui ;
- **prix périmé** (plus de 30 jours) : il ne témoigne plus de rien ;
- **prix atypique** : conservé et affiché ailleurs, mais on ne recommande pas un
  détour vers un prix dont on doute ;
- **station inactive** : elle n'existe plus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from psycopg.rows import dict_row

from carburant_api.requetes.connexion import DELAI_CONNEXION, Pool

AUTONOMIE_MAX_KM: Final = 1500.0
"""Plafond de bon sens. Au-dela, ce n'est plus une question d'autonomie."""


@dataclass(frozen=True, slots=True)
class RechercheMeilleure:
    """Les paramètres d'une recherche de meilleure station."""

    latitude: float
    longitude: float
    carburant: str
    rayon_geodesique_km: float
    """Déjà converti : autonomie x marge divisee par le facteur de detour."""


# `marts.est_suspect` lit la référence départementale matérialisée. Les stations
# sans département connu — la Corse historique, quelques stations du flux — ne sont
# jamais jugées atypiques, faute de médiane à laquelle les comparer : elles passent,
# et c'est le bon choix, mieux vaut une station de plus qu'un trou dans la carte.
_SQL = """
WITH point AS (
    SELECT ST_SetSRID(
               ST_MakePoint(%(lon)s::double precision, %(lat)s::double precision),
               4326
           )::geography AS g
),
candidates AS (
    SELECT s.id, s.adresse, s.ville, s.cp, s.code_departement, s.autoroute,
           s.enseigne, s.enseigne_source,
           ST_Y(s.geom::geometry) AS latitude,
           ST_X(s.geom::geometry) AS longitude,
           ST_Distance(s.geom, point.g) / 1000.0 AS distance_vol_oiseau_km
      FROM marts.dim_station s, point
     WHERE s.active
       AND ST_DWithin(s.geom, point.g, %(rayon_m)s::double precision)
),
dernier_prix AS (
    SELECT DISTINCT ON (f.station_id)
           f.station_id, f.prix, f.maj,
           marts.classe_fraicheur(f.maj) AS fraicheur
      FROM marts.fact_prix f
      JOIN candidates c ON c.id = f.station_id
     WHERE f.carburant = %(carburant)s::text
       -- Borne basse indispensable : sans elle, cette recherche fait un parcours
       -- d'index par station candidate et par partition -- 242 apres l'amorcage de
       -- l'historique -- puis trie vingt ans de changements de prix pour en garder
       -- un. Avec elle, PostgreSQL elague et il en reste trois.
       --
       -- Elle ne change rien au resultat : la clause `fraicheur <> 'perime'` plus bas
       -- ecartait deja tout ce que l'horizon exclut, celui-ci etant place un jour
       -- avant le seuil de peremption (`infra/migrations/011_horizon_recherche.sql`).
       AND f.maj >= marts.horizon_prix_exploitable()
     ORDER BY f.station_id, f.maj DESC
)
SELECT c.*, p.prix, p.maj, p.fraicheur,
       marts.est_suspect(p.prix, r.mediane, r.mad, r.stations) AS suspect
  FROM candidates c
  JOIN dernier_prix p ON p.station_id = c.id
  LEFT JOIN marts.reference_departementale r
         ON r.code_departement = c.code_departement
        AND r.carburant = %(carburant)s::text
 WHERE p.fraicheur <> 'perime'
   AND NOT marts.est_suspect(p.prix, r.mediane, r.mad, r.stations)
   AND NOT EXISTS (
           SELECT 1 FROM marts.rupture ru
            WHERE ru.station_id = c.id AND ru.carburant = %(carburant)s::text
       )
"""


async def candidates(pool: Pool, recherche: RechercheMeilleure) -> list[dict[str, Any]]:
    """Les stations atteignables qui vendent ce carburant à un prix exploitable."""
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(
            _SQL,
            {
                "lat": recherche.latitude,
                "lon": recherche.longitude,
                "rayon_m": recherche.rayon_geodesique_km * 1000.0,
                "carburant": recherche.carburant,
            },
        )
        return await curseur.fetchall()
