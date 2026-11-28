"""`/v1/stations/proches` : les stations autour d'un point.

C'est l'endpoint le plus sollicite du site : c'est lui qui repond a « ou faire le
plein ? ». Objectif de tenue : p95 < 300 ms sur le VPS. Mesure du 24/11/2026 sur les
vraies donnees (9 825 stations, 33 153 changements de prix, 15 partitions) : **11 ms**
pour un rayon de 10 km.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Query, Request, Response, status

from carburant_api.cache import poser_entetes
from carburant_api.calcul import cout
from carburant_api.erreurs import BASE_TYPE, ProblemeAPI
from carburant_api.requetes.meilleure import AUTONOMIE_MAX_KM, RechercheMeilleure
from carburant_api.requetes.meilleure import candidates as candidates_meilleure
from carburant_api.requetes.stations import (
    LIMITE_MAX,
    RAYON_MAX_KM,
    Recherche,
    Tri,
    fiche,
    historique,
    lire_meta,
    stations_proches,
)
from carburant_api.schemas.meilleure import Hypotheses, ReponseMeilleure, StationEvaluee
from carburant_api.schemas.station import (
    ChangementPrix,
    Enseigne,
    FicheStation,
    PrixCarburant,
    ReponseHistorique,
    ReponseStationsProches,
    Rupture,
    StationProche,
)
from carburant_api.temps import maintenant

routeur = APIRouter(prefix="/stations", tags=["stations"])

CARBURANTS: Final = ("gazole", "sp95", "e10", "sp98", "e85", "gplc")
"""Les six carburants publies par le flux. Rien d'autre n'existe."""

# La France metropolitaine plus la Corse. Le flux ne contient aucune station en
# outre-mer (docs/reconnaissance.md section 1.6) : une position aux Antilles ne
# renverra jamais rien, autant le dire franchement.
EMPRISE_LAT: Final = (41.0, 51.5)
EMPRISE_LON: Final = (-5.5, 10.0)


def _enseigne(ligne: Mapping[str, Any]) -> Enseigne | None:
    """L'enseigne d'une ligne de resultat, ou `None` quand on ne la connait pas.

    Partagee par la recherche et la fiche : deux constructions auraient fini par
    rendre deux formes differentes pour la meme donnee, et c'est exactement ce qui
    s'etait produit -- la recherche rendait un champ toujours vide.
    """
    if not ligne.get("enseigne"):
        return None
    score = ligne.get("enseigne_score")
    return Enseigne(
        nom=str(ligne["enseigne"]),
        source=str(ligne.get("enseigne_source") or "inconnue"),
        score=float(score) if score else None,
        objet_osm=ligne.get("enseigne_osm"),
    )


def _verifier_emprise(lat: float, lon: float) -> None:
    """Refuse une position hors de l'emprise couverte, en disant pourquoi.

    Le flux officiel ne contient aucune station d'outre-mer : une recherche aux
    Antilles ne renverra jamais rien. Autant le dire franchement plutot que de
    rendre une liste vide.
    """
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
                enseigne=_enseigne(ligne),
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
    _verifier_emprise(lat, lon)

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


def _evaluer(
    ligne: dict[str, Any], *, litres: float, consommation: float
) -> tuple[StationEvaluee, cout.Detail]:
    """Transforme une ligne de la base en station evaluee, cout compris."""
    vol_oiseau = float(ligne["distance_vol_oiseau_km"])
    routiere = cout.distance_routiere(vol_oiseau)
    detail = cout.detail(
        prix_eur_l=float(ligne["prix"]),
        distance_km=routiere,
        litres=litres,
        consommation_l_100km=consommation,
    )
    evaluee = StationEvaluee(
        id=int(ligne["id"]),
        adresse=ligne["adresse"],
        ville=ligne["ville"],
        cp=ligne["cp"],
        enseigne=ligne["enseigne"],
        autoroute=bool(ligne["autoroute"]),
        latitude=float(ligne["latitude"]),
        longitude=float(ligne["longitude"]),
        distance_vol_oiseau_km=round(vol_oiseau, 3),
        distance_routiere_km=round(routiere, 3),
        prix_eur_l=detail.prix_eur_l,
        maj=ligne["maj"],
        fraicheur=ligne["fraicheur"],
        cout_plein_eur=round(detail.cout_plein_eur, 2),
        cout_detour_eur=round(detail.cout_detour_eur, 2),
        cout_reel_eur=round(detail.cout_reel_eur, 2),
    )
    return evaluee, detail


@routeur.get(
    "/meilleure",
    summary="La station au cout reel le plus bas, detour compris",
    description=(
        "**La station la moins chere n'est pas toujours la moins chere.** Faire six "
        "kilometres de plus pour gagner trois centimes au litre coute plus que ca ne "
        "rapporte. Cet endpoint classe les stations sur le cout reel :\n\n"
        "    cout_reel = prix x litres + prix x (2 x distance x consommation / 100)\n\n"
        "**Ce qui est ecarte** : les carburants en rupture, les prix perimes, les prix "
        "atypiques -- conserves et affiches ailleurs, mais on ne recommande pas un "
        "detour vers un prix dont on doute -- et les stations hors d'atteinte.\n\n"
        "**Les hypotheses du calcul sont dans la reponse**, champ `hypotheses` : "
        "aller-retour, carburant du trajet valorise au prix de la station, distance "
        "routiere estimee. Un chiffre qu'on ne peut pas refaire soi-meme n'a pas sa "
        "place devant quelqu'un qui va rouler sur la foi de ce qu'on lui dit."
    ),
    response_model=ReponseMeilleure,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Parametres invalides (problem+json)."
        }
    },
)
async def meilleure(
    requete: Request,
    reponse: Response,
    lat: Annotated[float, Query(description="Latitude, en degres decimaux.", examples=[43.2726])],
    lon: Annotated[float, Query(description="Longitude, en degres decimaux.", examples=[5.3846])],
    carburant: Annotated[
        str, Query(description=f"Un des {', '.join(CARBURANTS)}.", examples=["gazole"])
    ],
    autonomie_km: Annotated[
        float,
        Query(
            gt=0,
            le=AUTONOMIE_MAX_KM,
            description=(
                "Autonomie restante annoncee par le vehicule. On n'en consomme que "
                "80 % : un tableau de bord est optimiste."
            ),
            examples=[80.0],
        ),
    ] = 80.0,
    litres: Annotated[
        float,
        Query(
            gt=0,
            le=200,
            description="Volume du plein. Valeur pre-remplie, a ajuster ; ce n'est pas une moyenne mesuree.",
            examples=[40.0],
        ),
    ] = cout.LITRES_PAR_DEFAUT,
    conso_l_100km: Annotated[
        float,
        Query(
            ge=0,
            le=50,
            description="Consommation du vehicule. Meme statut que `litres`.",
            examples=[7.0],
        ),
    ] = cout.CONSOMMATION_PAR_DEFAUT,
    limite: Annotated[
        int, Query(ge=1, le=20, description="Nombre de stations renvoyees.", examples=[5])
    ] = 5,
) -> ReponseMeilleure:
    """Classe les stations atteignables par cout reel."""
    if carburant not in CARBURANTS:
        raise ProblemeAPI(
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Carburant inconnu",
            detail=f"« {carburant} » n'existe pas. Valeurs acceptees : {', '.join(CARBURANTS)}.",
            type_=f"{BASE_TYPE}#carburant-inconnu",
        )
    _verifier_emprise(lat, lon)

    hypotheses = Hypotheses(
        facteur_detour=cout.FACTEUR_DETOUR,
        marge_autonomie=cout.MARGE_AUTONOMIE,
        litres=litres,
        consommation_l_100km=conso_l_100km,
    )

    # Le rayon de recherche est en distance geodesique, alors que l'autonomie se
    # depense sur la route : on divise par le facteur de detour, sinon on chercherait
    # trop loin et on ecarterait ensuite la plupart des candidates.
    rayon = (autonomie_km * cout.MARGE_AUTONOMIE) / cout.FACTEUR_DETOUR
    lignes = await candidates_meilleure(
        requete.app.state.pool,
        RechercheMeilleure(
            latitude=lat, longitude=lon, carburant=carburant, rayon_geodesique_km=rayon
        ),
    )

    evaluees = [_evaluer(ligne, litres=litres, consommation=conso_l_100km) for ligne in lignes]
    # Double garde-fou : le rayon a deja borne la recherche, mais la regle
    # d'atteignabilite est testee comme propriete et c'est elle qui fait foi.
    atteignables = [
        (e, d) for e, d in evaluees if cout.atteignable(d.distance_km, autonomie_km=autonomie_km)
    ]

    if not atteignables:
        corps = ReponseMeilleure(
            atteignables=0,
            avertissement=(
                f"Aucune station atteignable avec {autonomie_km:.0f} km d'autonomie. "
                "Essayez un autre carburant, ou verifiez votre position."
            ),
            hypotheses=hypotheses,
        )
        poser_entetes(reponse, corps, max_age=_duree_cache())
        return corps

    par_cout = sorted(atteignables, key=lambda paire: paire[1].cout_reel_eur)
    par_distance = min(atteignables, key=lambda paire: paire[1].distance_km)

    corps = ReponseMeilleure(
        meilleure=par_cout[0][0],
        la_plus_proche=par_distance[0],
        economie_eur=round(cout.economie(par_cout[0][1], par_distance[1]), 2),
        stations=[evaluee for evaluee, _ in par_cout[:limite]],
        atteignables=len(atteignables),
        hypotheses=hypotheses,
    )
    poser_entetes(reponse, corps, max_age=_duree_cache())
    return corps


@routeur.get(
    "/{station_id}",
    summary="Fiche complete d'une station",
    description=(
        "Tout ce qu'on sait d'une station : adresse, enseigne, services, horaires, et "
        "**tous** ses carburants.\n\n"
        "Contrairement a une recherche, une fiche ne cache rien : les prix perimes et "
        "les carburants en rupture y figurent, avec leur date et leur etat. Un prix de "
        "deux mois n'est pas une raison de faire comme s'il n'existait pas, c'est une "
        "raison de le dater.\n\n"
        "L'enseigne vient d'OpenStreetMap (licence ODbL) et porte la facon dont elle a "
        "ete trouvee : un rapprochement geographique merite plus de prudence qu'une "
        "correspondance d'identifiant officiel."
    ),
    response_model=FicheStation,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Station inconnue (problem+json)."}},
)
async def fiche_station(
    requete: Request,
    reponse: Response,
    station_id: Annotated[int, Path(description="Identifiant officiel.", examples=[13008003])],
) -> FicheStation:
    """La fiche d'une station."""
    station, prix = await fiche(requete.app.state.pool, station_id)
    if station is None:
        raise ProblemeAPI(
            statut=status.HTTP_404_NOT_FOUND,
            titre="Station inconnue",
            detail=(
                f"Aucune station ne porte l'identifiant {station_id}. Les identifiants "
                "sont ceux du flux officiel."
            ),
            type_=f"{BASE_TYPE}#station-inconnue",
        )

    enseigne = _enseigne(station)

    corps = FicheStation(
        id=int(station["id"]),
        adresse=station["adresse"],
        ville=station["ville"],
        cp=station["cp"],
        departement=station["departement"],
        code_departement=station["code_departement"],
        region=station["region"],
        autoroute=bool(station["autoroute"]),
        latitude=float(station["latitude"]),
        longitude=float(station["longitude"]),
        enseigne=enseigne,
        services=list(station["services"] or []),
        horaires=station["horaires"],
        prix=[
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
            for ligne in prix
        ],
        premiere_vue=station["premiere_vue"],
        derniere_vue=station["derniere_vue"],
        active=bool(station["active"]),
    )
    poser_entetes(reponse, corps, max_age=_duree_cache())
    return corps


@routeur.get(
    "/{station_id}/historique",
    summary="Historique des prix d'une station",
    description=(
        "Les changements de prix d'une station, du plus recent au plus ancien.\n\n"
        "Le grain de la base etant « un changement de prix », cet historique est "
        "**exactement ce que la source a publie** : aucun echantillonnage, aucun "
        "lissage, aucune interpolation. Entre deux changements, le prix n'a pas bouge."
    ),
    response_model=ReponseHistorique,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Station inconnue (problem+json)."}},
)
async def historique_station(
    requete: Request,
    reponse: Response,
    station_id: Annotated[int, Path(description="Identifiant officiel.", examples=[13008003])],
    carburant: Annotated[
        str | None, Query(description="Un seul carburant, ou tous si absent.", examples=["gazole"])
    ] = None,
    jours: Annotated[
        int, Query(ge=1, le=3650, description="Profondeur de l'historique.", examples=[90])
    ] = 365,
    limite: Annotated[
        int, Query(ge=1, le=2000, description="Nombre maximal de changements.", examples=[500])
    ] = 500,
) -> ReponseHistorique:
    """L'historique des prix d'une station."""
    if carburant is not None and carburant not in CARBURANTS:
        raise ProblemeAPI(
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Carburant inconnu",
            detail=f"« {carburant} » n'existe pas. Valeurs acceptees : {', '.join(CARBURANTS)}.",
            type_=f"{BASE_TYPE}#carburant-inconnu",
        )
    station, _ = await fiche(requete.app.state.pool, station_id)
    if station is None:
        raise ProblemeAPI(
            statut=status.HTTP_404_NOT_FOUND,
            titre="Station inconnue",
            detail=f"Aucune station ne porte l'identifiant {station_id}.",
            type_=f"{BASE_TYPE}#station-inconnue",
        )

    depuis = maintenant() - dt.timedelta(days=jours)
    lignes = await historique(
        requete.app.state.pool,
        station_id,
        carburant=carburant,
        depuis=depuis,
        limite=limite,
    )
    corps = ReponseHistorique(
        station_id=station_id,
        carburant=carburant,
        depuis=depuis,
        changements=[
            ChangementPrix(
                carburant=ligne["carburant"],
                prix_eur_l=float(ligne["prix"]),
                maj=ligne["maj"],
            )
            for ligne in lignes
        ],
        total=len(lignes),
    )
    poser_entetes(reponse, corps, max_age=_duree_cache())
    return corps
