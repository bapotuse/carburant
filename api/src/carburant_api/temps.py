"""L'instant present, en un seul endroit.

L'API n'a pas besoin du module de fuseau de l'ETL : les horodatages qu'elle lit
viennent de colonnes `timestamptz`, deja correctes. Le piege du `+00:00` mensonger de
la source est traite une fois pour toutes a l'entree du pipeline
(`carburant_etl.fuseau`), pas ici.

Ce module existe pour qu'un test puisse figer l'heure, et pour qu'aucun appel a
`datetime.now()` ne traine sans fuseau dans le code.
"""

from __future__ import annotations

import datetime as dt
from typing import Final
from zoneinfo import ZoneInfo

PARIS: Final = ZoneInfo("Europe/Paris")


def maintenant() -> dt.datetime:
    """L'instant present, en UTC."""
    return dt.datetime.now(tz=dt.UTC)


def en_heure_de_paris(instant: dt.datetime) -> dt.datetime:
    """Convertit un instant en heure de Paris, pour l'affichage et les agregats."""
    if instant.tzinfo is None:
        raise ValueError("instant naif : le fuseau doit etre explicite")
    return instant.astimezone(PARIS)
