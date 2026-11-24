"""Requetes SQL sur les stations.

SQL brut, pas d'ORM : les requetes geographiques et les agregats s'ecrivent mieux
ainsi, et on voit exactement ce qui part a la base. C'est aussi ce qui permet de
coller un `EXPLAIN ANALYZE` dans la documentation sans traduction.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Final, Literal

from psycopg.rows import dict_row

from carburant_api.requetes.connexion import DELAI_CONNEXION, Pool

RAYON_MAX_KM: Final = 50.0
"""Au-dela, la recherche n'a plus de sens : on ne fait pas 50 km pour economiser
quelques centimes, et la requete deviendrait couteuse."""

LIMITE_MAX: Final = 100
"""Plafond de pagination. Une liste plus longue ne se lit pas sur un telephone."""

type Tri = Literal["prix", "distance"]


@dataclass(frozen=True, slots=True)
class Recherche:
    """Les parametres d'une recherche de stations proches."""

    latitude: float
    longitude: float
    rayon_km: float
    carburant: str | None
    tri: Tri
    limite: int
    decalage: int
    # Les prix perimes (> 30 jours) sont exclus des recherches mais restent visibles
    # sur la fiche de la station. Les prix anciens, eux, sont gardes : les ecarter
    # priverait l'utilisateur de stations qui existent et vendent au prix affiche.
    inclure_perimes: bool = False


# Le `DISTINCT ON` prend le dernier changement de prix de chaque carburant. La vue
# `marts.prix_courant` fait la meme chose, mais on l'ecrit ici en toutes lettres pour
# pouvoir filtrer sur le carburant AVANT de chercher le dernier prix : sur une
# recherche mono-carburant, cela divise le travail par six.
# Les parametres portent un cast explicite : sans lui, PostgreSQL ne sait pas deduire
# le type de `%(carburant)s`, qui n'apparait que dans une comparaison a NULL et une
# egalite, et repond « could not determine data type of parameter ».
_SQL_PROCHES = """
WITH point AS (
    SELECT ST_SetSRID(
               ST_MakePoint(%(lon)s::double precision, %(lat)s::double precision),
               4326
           )::geography AS g
),
candidates AS (
    SELECT s.id, s.adresse, s.ville, s.cp, s.departement, s.code_departement,
           s.autoroute,
           ST_Y(s.geom::geometry) AS latitude,
           ST_X(s.geom::geometry) AS longitude,
           ST_Distance(s.geom, point.g) / 1000.0 AS distance_km
      FROM marts.dim_station s, point
     WHERE s.active
       AND ST_DWithin(s.geom, point.g, %(rayon_m)s::double precision)
),
prix AS (
    SELECT DISTINCT ON (f.station_id, f.carburant)
           f.station_id, f.carburant, f.prix, f.maj,
           marts.classe_fraicheur(f.maj) AS fraicheur
      FROM marts.fact_prix f
      JOIN candidates c ON c.id = f.station_id
     WHERE (%(carburant)s::text IS NULL OR f.carburant = %(carburant)s::text)
     ORDER BY f.station_id, f.carburant, f.maj DESC
),
retenues AS (
    SELECT c.*, p.carburant, p.prix, p.maj, p.fraicheur,
           r.type AS rupture_type, r.debut AS rupture_debut
      FROM candidates c
      JOIN prix p ON p.station_id = c.id
      LEFT JOIN marts.rupture r
             ON r.station_id = c.id AND r.carburant = p.carburant
     WHERE (%(inclure_perimes)s::boolean OR p.fraicheur <> 'perime')
       -- Un carburant en rupture est exclu des recherches, et affiche comme tel
       -- sur la fiche de la station.
       AND r.type IS NULL
)
SELECT * FROM retenues
 ORDER BY {ordre}
"""

_ORDRES: Final[dict[str, str]] = {
    # Prix croissant, puis distance : a prix egal, la plus proche d'abord. Les prix
    # nuls (carburant sans prix) passent en dernier.
    "prix": "prix ASC NULLS LAST, distance_km ASC, id",
    "distance": "distance_km ASC, prix ASC NULLS LAST, id",
}


async def stations_proches(pool: Pool, recherche: Recherche) -> tuple[list[dict[str, Any]], int]:
    """Les stations autour d'un point. Renvoie (lignes, nombre total de stations).

    Les lignes sont au grain station x carburant : l'appelant les regroupe par
    station. Le total compte les stations distinctes avant pagination.
    """
    ordre = _ORDRES[recherche.tri]
    requete = _SQL_PROCHES.format(ordre=ordre)

    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(
            requete,
            {
                "lat": recherche.latitude,
                "lon": recherche.longitude,
                "rayon_m": recherche.rayon_km * 1000.0,
                "carburant": recherche.carburant,
                "inclure_perimes": recherche.inclure_perimes,
            },
        )
        lignes = await curseur.fetchall()

    # `count(DISTINCT id) OVER ()` n'existe pas dans PostgreSQL. Comme on regroupe
    # de toute facon par station cote applicatif, on compte les identifiants
    # distincts ici plutot que d'ajouter une seconde requete.
    total = len({ligne["id"] for ligne in lignes})
    return lignes, total


@dataclass(frozen=True, slots=True)
class Meta:
    """Ce que `/v1/meta` expose sur l'etat des donnees."""

    derniere_collecte: dt.datetime | None
    stations_actives: int
    prix_connus: int
    carburants: list[str]


async def lire_meta(pool: Pool) -> Meta:
    """Etat des donnees servies : derniere collecte, volumes, carburants."""
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(
            """
                SELECT (SELECT max(fin) FROM meta.execution_etl WHERE statut = 'succes')
                           AS derniere_collecte,
                       (SELECT count(*) FROM marts.dim_station WHERE active)
                           AS stations_actives,
                       (SELECT count(*) FROM marts.fact_prix) AS prix_connus,
                       (SELECT array_agg(code ORDER BY ordre) FROM marts.dim_carburant)
                           AS carburants
            """
        )
        ligne = await curseur.fetchone()

    if ligne is None:  # pragma: no cover - la requete rend toujours une ligne
        return Meta(None, 0, 0, [])
    return Meta(
        derniere_collecte=ligne["derniere_collecte"],
        stations_actives=int(ligne["stations_actives"] or 0),
        prix_connus=int(ligne["prix_connus"] or 0),
        carburants=list(ligne["carburants"] or []),
    )
