"""Acces a la base : un pool de connexions, partage par l'application.

SQLAlchemy Core et psycopg 3, pas d'ORM. Le pool est ouvert au demarrage de
l'application et ferme a son arret, pour qu'une requete n'ait jamais a etablir sa
propre connexion.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from typing import Any, Final

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

type Pool = AsyncConnectionPool[AsyncConnection[Any]]
"""Le pool tel que psycopg le type : parametre par le type de connexion."""

DELAI_CONNEXION: Final = 3.0
"""Secondes avant de considerer la base injoignable. Court : /v1/sante doit repondre
vite, meme quand tout va mal."""


def url_base() -> str:
    """URL de connexion, lue dans l'environnement. Aucune valeur par defaut."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL absente. Copier .env.example en .env et la renseigner.")
    return url


def creer_pool() -> Pool:
    """Cree le pool sans l'ouvrir : l'ouverture se fait dans le cycle de vie de l'app."""
    return AsyncConnectionPool(
        url_base(),
        min_size=1,
        max_size=8,
        open=False,
        timeout=DELAI_CONNEXION,
    )


@dataclass(frozen=True, slots=True)
class EtatBase:
    """Ce que /v1/sante a besoin de savoir sur la base."""

    joignable: bool
    derniere_collecte_reussie: dt.datetime | None


async def lire_etat(pool: Pool) -> EtatBase:
    """Interroge la base : repond-elle, et quand a-t-elle recu sa derniere collecte ?

    Ne leve jamais : une base injoignable est une reponse, pas une erreur. C'est
    precisement ce que /v1/sante doit pouvoir rapporter.
    """
    try:
        async with pool.connection(timeout=DELAI_CONNEXION) as connexion:
            curseur = await connexion.execute(
                "SELECT max(fin) FROM meta.execution_etl WHERE statut = 'succes'"
            )
            ligne = await curseur.fetchone()
    except Exception:
        return EtatBase(joignable=False, derniere_collecte_reussie=None)

    derniere = ligne[0] if ligne else None
    return EtatBase(
        joignable=True,
        derniere_collecte_reussie=derniere if isinstance(derniere, dt.datetime) else None,
    )
