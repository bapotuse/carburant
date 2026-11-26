"""Lecture des agregats journaliers et des facteurs d'emission.

Ces deux tables sont calculees par l'ETL ; l'API ne fait que les lire. C'est
volontaire : une moyenne ne doit pas etre recalculee a chaque requete, et surtout
pas differemment selon l'appelant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from psycopg.rows import dict_row

from carburant_api.requetes.connexion import DELAI_CONNEXION, Pool

JOURS_MAX: Final = 3650
"""Dix ans. Au-dela, une courbe sur un telephone ne veut plus rien dire."""


@dataclass(frozen=True, slots=True)
class RechercheTendance:
    """Les parametres d'une serie temporelle."""

    carburant: str
    dimension: str
    """`france`, `departement` ou `reseau`."""
    valeur: str
    """`''` pour la France entiere, un code de departement, ou `autoroute`/`route`."""
    jours: int


_SQL_SERIE = """
SELECT jour, stations, exclus, prix_min, prix_median, prix_moyen, prix_max
  FROM marts.agregat_prix_jour
 WHERE carburant = %(carburant)s::text
   AND dimension = %(dimension)s::text
   AND valeur    = %(valeur)s::text
   AND jour >= (current_date - %(jours)s::integer)
 ORDER BY jour
"""

_SQL_FACTEURS = """
SELECT carburant, valeur, unite, nom_base, nom_attribut, localisation,
       statut, periode_validite, version_base, url
  FROM marts.facteur_emission_courant
 WHERE (%(carburant)s::text IS NULL OR carburant = %(carburant)s::text)
 ORDER BY carburant
"""


async def serie(pool: Pool, recherche: RechercheTendance) -> list[dict[str, Any]]:
    """La serie journaliere d'un carburant sur un decoupage donne."""
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(
            _SQL_SERIE,
            {
                "carburant": recherche.carburant,
                "dimension": recherche.dimension,
                "valeur": recherche.valeur,
                "jours": recherche.jours,
            },
        )
        return await curseur.fetchall()


async def facteurs_emission(pool: Pool, carburant: str | None = None) -> list[dict[str, Any]]:
    """Les facteurs d'emission en vigueur, avec leur provenance complete."""
    async with (
        pool.connection(timeout=DELAI_CONNEXION) as connexion,
        connexion.cursor(row_factory=dict_row) as curseur,
    ):
        await curseur.execute(_SQL_FACTEURS, {"carburant": carburant})
        return await curseur.fetchall()
