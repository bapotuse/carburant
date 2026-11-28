"""`/v1/anecdotes/du-jour` : les chiffres du jour, avec leurs seuils.

Un endpoint, quatre anecdotes, quatre requêtes indépendantes. Elles sont lancées
**en parallèle** : les quatre lisent des tables différentes et ne s'attendent pas.

Le choix important est négatif : aucune anecdote n'est approximée pour remplir la
page. Sous son seuil, elle passe dans `indisponibles` avec sa raison et sa mesure.
C'est la règle de `docs/specs/web.md` — « pas de "historiquement" avec trois
semaines d'historique » — et c'est aussi ce qui rend la page honnête le jour où la
base est jeune.
"""

from __future__ import annotations

import asyncio
import os
from typing import Annotated, Any, Final

from fastapi import APIRouter, Query, Request, Response, status

from carburant_api.cache import poser_entetes
from carburant_api.erreurs import BASE_TYPE, ProblemeAPI
from carburant_api.requetes.anecdotes import (
    Indisponible,
    departement_moins_cher,
    ecart_du_jour,
    jour_semaine_moins_cher,
    surcout_autoroute,
)
from carburant_api.schemas.anecdotes import AnecdoteIndisponible, ReponseAnecdotes
from carburant_api.temps import maintenant

routeur = APIRouter(tags=["anecdotes"])

CARBURANTS: Final = ("gazole", "sp95", "e10", "sp98", "e85", "gplc")


def _duree_cache() -> int:
    """Un quart d'heure : l'écart du jour bouge à chaque collecte, les trois autres non.

    On cale la durée sur la plus volatile des quatre plutôt que de servir un écart
    du jour vieux d'une heure.
    """
    return int(os.environ.get("API_CACHE_ANECDOTES_SECONDES", "900"))


@routeur.get(
    "/anecdotes/du-jour",
    summary="Les chiffres du jour",
    description=(
        "Quatre anecdotes calculees depuis la base, pour un carburant :\n\n"
        "1. **ecart_du_jour** — l'ecart entre la station la moins chere et la plus "
        "chere de France aujourd'hui, les deux stations nommees ;\n"
        "2. **departement_moins_cher** — sur les sept derniers jours calcules ;\n"
        "3. **surcout_autoroute** — ce que coute en plus un plein de 50 L sur "
        "autoroute ;\n"
        "4. **jour_semaine_moins_cher** — le jour de la semaine historiquement le "
        "moins cher, **tendance de fond retiree** : le prix est passe de 1,07 EUR a "
        "1,86 EUR en seize ans, et moyenner les prix par jour de la semaine "
        "mesurerait cette hausse, pas l'effet du jour.\n\n"
        "**Chaque anecdote a un seuil minimal de donnees.** Sous son seuil, elle n'est "
        "pas approximee : elle apparait dans `indisponibles` avec sa raison et la "
        "mesure obtenue. Sur une base fraichement amorcee, les anecdotes historiques "
        "sont donc absentes, et elles le disent."
    ),
    response_model=ReponseAnecdotes,
    responses={422: {"description": "Carburant inconnu."}},
)
async def anecdotes_du_jour(
    requete: Request,
    reponse: Response,
    carburant: Annotated[
        str,
        Query(description="Code du carburant.", examples=["gazole"]),
    ] = "gazole",
) -> ReponseAnecdotes:
    """Les quatre anecdotes calculables pour ce carburant."""
    if carburant not in CARBURANTS:
        raise ProblemeAPI(
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Carburant inconnu",
            detail=f"« {carburant} » n'existe pas. Valeurs acceptees : {', '.join(CARBURANTS)}.",
            type_=f"{BASE_TYPE}#carburant-inconnu",
        )

    pool = requete.app.state.pool
    # Les quatre requetes lisent des tables differentes : rien ne justifie de les
    # enchainer. Le pool les sert en parallele.
    ecart, departement, autoroute, jour = await asyncio.gather(
        ecart_du_jour(pool, carburant),
        departement_moins_cher(pool, carburant),
        surcout_autoroute(pool, carburant),
        jour_semaine_moins_cher(pool, carburant),
    )

    resultats: dict[str, Any] = {}
    indisponibles: list[AnecdoteIndisponible] = []
    for cle, resultat in (
        ("ecart_du_jour", ecart),
        ("departement_moins_cher", departement),
        ("surcout_autoroute", autoroute),
        ("jour_semaine_moins_cher", jour),
    ):
        if isinstance(resultat, Indisponible):
            indisponibles.append(
                AnecdoteIndisponible(
                    cle=resultat.cle, raison=resultat.raison, mesure=resultat.mesure
                )
            )
        else:
            resultats[cle] = resultat

    charge = ReponseAnecdotes(
        carburant=carburant,
        calcule_le=maintenant(),
        indisponibles=indisponibles,
        **resultats,
    )
    poser_entetes(reponse, charge, max_age=_duree_cache())
    return charge
