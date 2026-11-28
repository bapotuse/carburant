"""`/v1/meta` : l'etat des donnees servies.

Ce que le site affiche en bas de page (« derniere collecte il y a 7 minutes ») et ce
qu'un recruteur regarde en premier pour savoir si le projet tourne vraiment.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from carburant_api.cache import poser_entetes
from carburant_api.requetes.stations import lire_meta
from carburant_api.temps import maintenant
from carburant_api.version import VERSION

routeur = APIRouter(tags=["service"])


class Source(BaseModel):
    """Une source de donnees, avec sa licence et son attribution."""

    nom: str
    url: str
    licence: str
    attribution: str


SOURCES = [
    Source(
        nom="Prix des carburants en France - Flux instantane v2",
        url="https://data.economie.gouv.fr/explore/dataset/prix-des-carburants-en-france-flux-instantane-v2/",
        licence="Licence Ouverte 2.0 (Etalab)",
        attribution="Ministeres economiques et financiers",
    ),
    Source(
        nom="Geocodage Geoplateforme",
        url="https://data.geopf.fr/geocodage/search",
        licence="Licence Ouverte 2.0 (Etalab)",
        attribution="IGN",
    ),
    # L'attribution d'OpenStreetMap est **obligatoire** sous licence ODbL, partout ou
    # une enseigne est affichee. Elle est donc declaree ici, et le pied de page du
    # site la reprend.
    Source(
        nom="Enseignes des stations",
        url="https://www.openstreetmap.org/copyright",
        licence="Open Database License (ODbL)",
        attribution="(c) les contributeurs d'OpenStreetMap",
    ),
    Source(
        nom="Facteurs d'emission - Base Carbone",
        url="https://data.ademe.fr/datasets/base-carbone(r)",
        licence="Licence Ouverte 2.0 (Etalab)",
        attribution="ADEME",
    ),
]


class ReponseMeta(BaseModel):
    """Etat des donnees et des sources."""

    derniere_collecte: dt.datetime | None = Field(
        default=None,
        description="Instant de la derniere collecte reussie, en UTC.",
        examples=["2026-11-24T19:45:00Z"],
    )
    age_derniere_collecte_minutes: Annotated[int, Field(ge=0)] | None = Field(
        default=None, description="Age de cette collecte, en minutes.", examples=[7]
    )
    stations_actives: int = Field(
        description="Stations vues lors des dernieres collectes.", examples=[9825]
    )
    prix_connus_environ: int = Field(
        description=(
            "**Estimation** du nombre de changements de prix historises, lue dans les "
            "statistiques de PostgreSQL. Le grain est le changement, pas la collecte : "
            "une station qui ne bouge pas son prix n'ajoute rien.\n\n"
            "Pourquoi une estimation : les compter vraiment demande de parcourir "
            "64 millions de lignes sur 242 partitions, soit une trentaine de secondes. "
            "Le chiffre sert a dire « environ 64 millions » en bas de page, pas a "
            "etre additionne. A afficher avec « environ »."
        ),
        examples=[64062124],
    )
    carburants: list[str] = Field(
        description="Les carburants publies par la source.",
        examples=[["gazole", "sp95", "e10", "sp98", "e85", "gplc"]],
    )
    couverture: str = Field(
        description="Ce que les donnees couvrent, et ce qu'elles ne couvrent pas."
    )
    sources: list[Source]
    version: str = Field(examples=[VERSION])


COUVERTURE = (
    "France metropolitaine et Corse. Le flux officiel ne contient aucune station "
    "d'outre-mer, ni le nom ou l'enseigne des stations : les enseignes viennent "
    "d'OpenStreetMap, qui en couvre 99,4 % (mesure du 26/11/2026). Une station sans "
    "enseigne connue s'affiche par son adresse."
)


@routeur.get(
    "/meta",
    summary="Etat des donnees et des sources",
    description=(
        "Derniere collecte, volumes, carburants publies, limites de couverture et "
        "attributions. C'est ici qu'on verifie que les donnees affichees sont "
        "fraiches, et d'ou elles viennent."
    ),
    response_model=ReponseMeta,
)
async def meta(requete: Request, reponse: Response) -> ReponseMeta:
    """Etat des donnees servies."""
    etat = await lire_meta(requete.app.state.pool)

    age: int | None = None
    if etat.derniere_collecte is not None:
        ecart = maintenant() - etat.derniere_collecte
        age = max(0, int(ecart.total_seconds() // 60))

    corps = ReponseMeta(
        derniere_collecte=etat.derniere_collecte,
        age_derniere_collecte_minutes=age,
        stations_actives=etat.stations_actives,
        prix_connus_environ=etat.prix_connus_environ,
        carburants=etat.carburants,
        couverture=COUVERTURE,
        sources=SOURCES,
        version=VERSION,
    )
    poser_entetes(reponse, corps, max_age=int(os.environ.get("API_CACHE_PRIX_SECONDES", "900")))
    return corps
