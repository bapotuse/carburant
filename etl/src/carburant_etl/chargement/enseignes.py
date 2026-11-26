"""Rapprochement des enseignes OpenStreetMap avec nos stations.

Deux passes, dans cet ordre, et l'ordre fait tout.

**1. Par l'identifiant officiel.** 80,5 % des points `amenity=fuel` de France portent
le tag `ref:FR:prix-carburants`, qui est l'identifiant de station du flux que nous
collectons. C'est une jointure sur cle : score 1,0, aucune place pour le doute.

**2. Par la geographie, pour le reliquat seulement.** Les stations non rapprochees a
la premiere passe sont confrontees au point OSM le plus proche **encore libre**, dans
un rayon de 150 m. Le score decroit avec la distance : plus loin, moins sur.

Pourquoi « encore libre » : sans cela, un point OSM deja rapproche par son identifiant
pourrait l'etre une seconde fois, geographiquement, a une station voisine. Deux
stations d'une meme aire d'autoroute se retrouveraient avec la meme enseigne au motif
qu'elles sont a 80 m l'une de l'autre.

Rien n'est invente : une station sans correspondance reste sans enseigne, et
s'affiche par son adresse. Le taux de couverture est mesure et destine a etre affiche
(`marts.couverture_enseigne`).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import psycopg

from carburant_etl.chargement.verrou import exclusif
from carburant_etl.sources.osm import PointOsm

journal = logging.getLogger("carburant.enseignes")

RAYON_METRES: Final = 150.0
"""Au-dela, ce n'est plus la meme station. Une aire d'autoroute en contient deux a
80 m l'une de l'autre : aller plus loin melangerait les voisines."""

SCORE_SPATIAL_MAX: Final = 0.90
SCORE_SPATIAL_MIN: Final = 0.50
"""Un rapprochement geographique ne vaut jamais un rapprochement par identifiant :
son score plafonne a 0,90 a distance nulle et tombe a 0,50 au bord du rayon."""


@dataclass(frozen=True, slots=True)
class ResultatEnseignes:
    """Ce qu'une passe de rapprochement a produit."""

    points_osm: int
    par_reference: int
    par_distance: int
    stations_actives: int

    @property
    def couverture_pourcent(self) -> float:
        total = self.par_reference + self.par_distance
        return 100.0 * total / self.stations_actives if self.stations_actives else 0.0


_TABLE = """
CREATE TEMPORARY TABLE osm (
    cle        text PRIMARY KEY,
    reference  text,
    enseigne   text,
    wikidata   text,
    geom       geography(Point, 4326) NOT NULL
) ON COMMIT DROP
"""

_PAR_REFERENCE = """
UPDATE marts.dim_station s
   SET enseigne          = o.enseigne,
       enseigne_wikidata = o.wikidata,
       enseigne_osm      = o.cle,
       enseigne_source   = 'osm-reference',
       enseigne_score    = 1.0,
       enseigne_vue_le   = %(vue)s
  FROM osm o
 WHERE o.reference IS NOT NULL
   AND o.enseigne IS NOT NULL
   -- Les identifiants du flux sont des entiers ; OSM les ecrit en texte, parfois
   -- avec des espaces. On compare sur du texte normalise plutot que de risquer une
   -- conversion qui echouerait sur une valeur mal saisie.
   AND btrim(o.reference) = s.id::text
"""

# La passe spatiale ne regarde que les stations encore sans enseigne et les points
# OSM encore libres. `DISTINCT ON (s.id)` garde, pour chaque station, le point le
# plus proche ; le second `DISTINCT ON` empeche qu'un meme point serve deux fois.
_PAR_DISTANCE = f"""
WITH candidats AS (
    SELECT DISTINCT ON (s.id)
           s.id AS station_id, o.cle, o.enseigne, o.wikidata,
           ST_Distance(s.geom, o.geom) AS metres
      FROM marts.dim_station s
      JOIN osm o
        ON ST_DWithin(s.geom, o.geom, %(rayon)s)
     WHERE s.enseigne IS NULL
       AND s.active
       AND o.enseigne IS NOT NULL
       AND o.cle NOT IN (SELECT enseigne_osm FROM marts.dim_station
                          WHERE enseigne_osm IS NOT NULL)
     ORDER BY s.id, ST_Distance(s.geom, o.geom)
),
retenus AS (
    SELECT DISTINCT ON (cle) station_id, cle, enseigne, wikidata, metres
      FROM candidats
     ORDER BY cle, metres
)
UPDATE marts.dim_station s
   SET enseigne          = r.enseigne,
       enseigne_wikidata = r.wikidata,
       enseigne_osm      = r.cle,
       enseigne_source   = 'osm-spatial',
       enseigne_score    = round(
           ({SCORE_SPATIAL_MAX} - ({SCORE_SPATIAL_MAX} - {SCORE_SPATIAL_MIN})
            * r.metres / %(rayon)s)::numeric, 2),
       enseigne_vue_le   = %(vue)s
  FROM retenus r
 WHERE s.id = r.station_id
"""


def rapprocher(
    connexion: psycopg.Connection[tuple[object, ...]],
    points: Sequence[PointOsm],
    *,
    rayon_metres: float = RAYON_METRES,
) -> ResultatEnseignes:
    """Rapproche les enseignes, par identifiant puis par distance. Idempotent."""
    if not points:
        raise ValueError("aucun point OpenStreetMap a rapprocher")
    vue = dt.datetime.now(tz=dt.UTC)

    with (
        exclusif(connexion, operation="enseignes"),
        connexion.transaction(),
        connexion.cursor() as curseur,
    ):
        curseur.execute(_TABLE)
        with curseur.copy(
            "COPY osm (cle, reference, enseigne, wikidata, geom) FROM STDIN"
        ) as copie:
            for point in points:
                copie.write_row(
                    (
                        point.cle,
                        point.reference_officielle,
                        point.enseigne,
                        point.wikidata,
                        f"SRID=4326;POINT({point.longitude} {point.latitude})",
                    )
                )

        # Les deux passes repartent de zero : relancer apres une mise a jour d'OSM
        # doit pouvoir retirer une enseigne qui a disparu, pas seulement en ajouter.
        curseur.execute(
            "UPDATE marts.dim_station SET enseigne = NULL, enseigne_wikidata = NULL, "
            "enseigne_osm = NULL, enseigne_source = NULL, enseigne_score = NULL "
            "WHERE enseigne_source LIKE 'osm-%'"
        )

        curseur.execute(_PAR_REFERENCE, {"vue": vue})
        par_reference = curseur.rowcount

        curseur.execute(_PAR_DISTANCE, {"vue": vue, "rayon": rayon_metres})
        par_distance = curseur.rowcount

        curseur.execute("SELECT count(*) FROM marts.dim_station WHERE active")
        ligne = curseur.fetchone()
        actives = int(ligne[0]) if ligne and isinstance(ligne[0], int) else 0

    resultat = ResultatEnseignes(
        points_osm=len(points),
        par_reference=par_reference,
        par_distance=par_distance,
        stations_actives=actives,
    )
    journal.info(
        "enseignes : %d par identifiant, %d par distance, soit %.1f %% des %d stations actives",
        resultat.par_reference,
        resultat.par_distance,
        resultat.couverture_pourcent,
        resultat.stations_actives,
    )
    return resultat
