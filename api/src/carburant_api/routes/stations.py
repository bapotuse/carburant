"""`/v1/stations/proches` : les stations autour d'un point.

C'est l'endpoint le plus sollicite du site : c'est lui qui repond a « ou faire le
plein ? ». Objectif de tenue : p95 < 300 ms sur le VPS. Mesure du 24/11/2026 sur les
vraies donnees (9 825 stations, 33 153 changements de prix, 15 partitions) : **11 ms**
pour un rayon de 10 km.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Final

from fastapi import APIRouter, Query, Request, Response, status

from carburant_api.cache import poser_entetes
from carburant_api.erreurs import BASE_TYPE, ProblemeAPI
from carburant_api.requetes.stations import (
    LIMITE_MAX,
    RAYON_MAX_KM,
    Recherche,
    Tri,
    lire_meta,
    stations_proches,
)
from carburant_api.schemas.station import (
    PrixCarburant,
    ReponseStationsProches,
    Rupture,
    StationProche,
)

routeur = APIRouter(prefix="/stations", tags=["stations"])

CARBURANTS: Final = ("gazole", "sp95", "e10", "sp98", "e85", "gplc")
"""Les six carburants publies par le flux. Rien d'autre n'existe."""

# La France metropolitaine plus la Corse. Le flux ne contient aucune station en
# outre-mer (docs/reconnaissance.md section 1.6) : une position aux Antilles ne
# renverra jamais rien, autant le dire franchement.
EMPRISE_LAT: Final = (41.0, 51.5)
EMPRISE_LON: Final = (-5.5, 10.0)


def _duree_cache() -> int:
    """Duree de cache des prix, alignee sur la cadence de collecte."""
    return int(os.environ.get("API_CACHE_PRIX_SECONDES", "900"))


def _regrouper(lignes: list[dict[str, Any]]) -> list[StationProche]:
    """Passe du grain station x carburant au grain station.

    La requete rend une ligne par couple ; l'API rend une station avec ses prix.
    L'ordre des lignes porte deja le tri : on le preserve.
    """
    par_station: dict[int, StationProche] = {}
    for ligne in lignes:
        identifiant = int(ligne["id"])
        station = par_station.get(identifiant)
        if station is None:
            station = StationProche(
                id=identifiant,
                adresse=ligne["adresse"],
                ville=ligne["ville"],
                cp=ligne["cp"],
                departement=ligne["departement"],
                code_departement=ligne["code_departement"],
                autoroute=bool(ligne["autoroute"]),
                latitude=float(ligne["latitude"]),
                longitude=float(ligne["longitude"]),
                distance_km=round(float(ligne["distance_km"]), 3),
                prix=[],
            )
            par_station[identifiant] = station

        station.prix.append(
            PrixCarburant(
                carburant=ligne["carburant"],
                prix_eur_l=float(ligne["prix"]) if ligne["prix"] is not None else None,
                maj=ligne["maj"],
                fraicheur=ligne["fraicheur"],
                rupture=(
                    Rupture(type=ligne["rupture_type"], debut=ligne["rupture_debut"])
                    if ligne["rupture_type"]
                    else None
                ),
            )
        )
    return list(par_station.values())


@routeur.get(
    "/proches",
    summary="Stations autour d'un point",
    description=(
        "Renvoie les stations dans un rayon donne, triees par prix ou par distance.\n\n"
        "**Ce qui est ecarte** : les stations inactives, les carburants declares en "
        "rupture, et les prix perimes -- ceux dont le dernier changement remonte a "
        "plus de 30 jours. Les prix *anciens* (7 a 30 jours) sont **gardes** : les "
        "ecarter priverait l'utilisateur de stations qui existent et vendent au prix "
        "affiche. Chaque prix porte sa date et sa classe de fraicheur, a afficher.\n\n"
        "La distance est a vol d'oiseau. Le trajet reel est plus long : "
        "`/v1/stations/meilleure` tiendra compte du detour."
    ),
    response_model=ReponseStationsProches,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Parametres invalides (problem+json)."
        }
    },
)
async def proches(
    requete: Request,
    reponse: Response,
    lat: Annotated[
        float,
        Query(
            description="Latitude du point de depart, en degres decimaux.",
            examples=[43.2726],
        ),
    ],
    lon: Annotated[
        float,
        Query(
            description="Longitude du point de depart, en degres decimaux.",
            examples=[5.3846],
        ),
    ],
    rayon_km: Annotated[
        float,
        Query(
            gt=0,
            le=RAYON_MAX_KM,
            description="Rayon de recherche en kilometres.",
            examples=[10.0],
        ),
    ] = 10.0,
    carburant: Annotated[
        str | None,
        Query(
            description=f"Limite la recherche a un carburant. Valeurs : {', '.join(CARBURANTS)}.",
            examples=["gazole"],
        ),
    ] = None,
    tri: Annotated[
        Tri,
        Query(description="`prix` du moins cher au plus cher, ou `distance`."),
    ] = "prix",
    limite: Annotated[
        int,
        Query(ge=1, le=LIMITE_MAX, description="Nombre maximal de stations renvoyees."),
    ] = 20,
    decalage: Annotated[
        int, Query(ge=0, description="Nombre de stations a sauter (pagination).")
    ] = 0,
) -> ReponseStationsProches:
    """Les stations autour d'un point, triees par prix ou par distance."""
    if not (EMPRISE_LAT[0] <= lat <= EMPRISE_LAT[1] and EMPRISE_LON[0] <= lon <= EMPRISE_LON[1]):
        raise ProblemeAPI(
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Position hors de France metropolitaine",
            detail=(
                f"La position ({lat}, {lon}) est hors de l'emprise couverte. Le flux "
                "officiel ne contient que la France metropolitaine et la Corse : "
                "aucune station d'outre-mer n'y figure."
            ),
            type_=f"{BASE_TYPE}#position-hors-emprise",
        )

    if carburant is not None and carburant not in CARBURANTS:
        raise ProblemeAPI(
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Carburant inconnu",
            detail=(
                f"'{carburant}' n'est pas un carburant publie. "
                f"Valeurs acceptees : {', '.join(CARBURANTS)}."
            ),
            type_=f"{BASE_TYPE}#carburant-inconnu",
            extra={"carburants_acceptes": list(CARBURANTS)},
        )

    pool = requete.app.state.pool
    lignes, total = await stations_proches(
        pool,
        Recherche(
            latitude=lat,
            longitude=lon,
            rayon_km=rayon_km,
            carburant=carburant,
            tri=tri,
            limite=limite,
            decalage=decalage,
        ),
    )

    stations = _regrouper(lignes)[decalage : decalage + limite]
    meta = await lire_meta(pool)

    corps = ReponseStationsProches(
        stations=stations,
        total=total,
        rayon_km=rayon_km,
        carburant=carburant,
        tri=tri,
        derniere_collecte=meta.derniere_collecte,
    )
    poser_entetes(reponse, corps, max_age=_duree_cache())
    return corps
