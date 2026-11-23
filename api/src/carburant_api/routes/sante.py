"""`/v1/sante` : l'etat du service, lisible par un humain comme par une sonde.

La regle est simple : cet endpoint ne ment pas. Si la base ne repond pas, il renvoie
503, meme si le processus web, lui, va parfaitement bien.
"""

from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from carburant_api.requetes.connexion import lire_etat
from carburant_api.temps import maintenant
from carburant_api.version import VERSION

routeur = APIRouter(tags=["service"])


def age_max_minutes() -> int:
    """Age maximal de la derniere collecte reussie avant de passer en degrade."""
    return int(os.environ.get("API_SANTE_AGE_MAX_MINUTES", "60"))


class Sante(BaseModel):
    """Etat de sante du service."""

    statut: Literal["ok", "degrade"] = Field(
        description=(
            "`ok` si la base repond **et** que la derniere collecte reussie est plus "
            "recente que le seuil configure. `degrade` sinon, avec un code 503."
        ),
        examples=["ok"],
    )
    base_joignable: bool = Field(description="La base de donnees repond-elle ?")
    schema_pret: bool = Field(
        description=(
            "Les migrations ont-elles ete appliquees ? Une base qui repond avec un "
            "schema absent n'est pas la meme panne qu'une base injoignable : la "
            "reparation est `make migrate`, pas un redemarrage."
        )
    )
    age_derniere_collecte_minutes: Annotated[int, Field(ge=0)] | None = Field(
        default=None,
        description=(
            "Age de la derniere collecte **reussie**, en minutes. `null` si aucune "
            "collecte n'a encore abouti."
        ),
        examples=[7],
    )
    age_max_minutes: int = Field(
        description="Seuil au dela duquel le service se declare degrade.",
        examples=[60],
    )
    version: str = Field(description="Version de l'API.", examples=[VERSION])


@routeur.get(
    "/sante",
    summary="Etat de sante du service",
    description=(
        "Renvoie 200 si la base repond et que la derniere collecte reussie est plus "
        "recente que le seuil configure, 503 sinon. Destine aux sondes de "
        "surveillance : la reponse n'est jamais mise en cache."
    ),
    responses={
        status.HTTP_200_OK: {"description": "Le service est operationnel."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Base injoignable, ou donnees trop vieilles."
        },
    },
)
async def sante(requete: Request, reponse: Response) -> Sante:
    """Etat de sante, verifie pour de vrai contre la base."""
    reponse.headers["Cache-Control"] = "no-store"

    etat = await lire_etat(requete.app.state.pool)
    seuil = age_max_minutes()

    age: int | None = None
    if etat.derniere_collecte_reussie is not None:
        ecart = maintenant() - etat.derniere_collecte_reussie
        age = max(0, int(ecart.total_seconds() // 60))

    # Au Jalon 0 aucune collecte n'a encore eu lieu : une base joignable suffit a dire
    # que le service est en etat. Des que la premiere collecte aura abouti, un age
    # au-dela du seuil fera basculer en degrade.
    frais = age is None or age <= seuil
    bon = etat.joignable and etat.schema_pret and frais

    if not bon:
        reponse.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return Sante(
        statut="ok" if bon else "degrade",
        base_joignable=etat.joignable,
        schema_pret=etat.schema_pret,
        age_derniere_collecte_minutes=age,
        age_max_minutes=seuil,
        version=VERSION,
    )
