"""`/v1/tendances` et `/v1/empreinte` : les series et l'empreinte carbone.

Les deux lisent des tables calculees par l'ETL plutot que de recalculer a la volee.
Une moyenne ne doit pas dependre de qui la demande ni de quand.
"""

from __future__ import annotations

import os
from typing import Annotated, Final

from fastapi import APIRouter, Query, Request, Response, status

from carburant_api.cache import poser_entetes
from carburant_api.erreurs import BASE_TYPE, ProblemeAPI
from carburant_api.requetes.tendances import (
    JOURS_MAX,
    RechercheTendance,
    facteurs_emission,
    serie,
)
from carburant_api.schemas.tendances import (
    Empreinte,
    FacteurEmission,
    PointSerie,
    ReponseComparaison,
    ReponseEmpreinte,
    ReponseTendance,
)

routeur = APIRouter(tags=["tendances"])

CARBURANTS: Final = ("gazole", "sp95", "e10", "sp98", "e85", "gplc")

DIMENSIONS: Final = ("france", "departement", "reseau")

LITRES_MAX: Final = 500.0


def _duree_cache_tendances() -> int:
    """Une heure : les agregats ne bougent qu'une fois par jour."""
    return int(os.environ.get("API_CACHE_TENDANCES_SECONDES", "3600"))


def _verifier_carburant(carburant: str) -> None:
    if carburant not in CARBURANTS:
        raise ProblemeAPI(
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Carburant inconnu",
            detail=f"« {carburant} » n'existe pas. Valeurs acceptees : {', '.join(CARBURANTS)}.",
            type_=f"{BASE_TYPE}#carburant-inconnu",
        )


@routeur.get(
    "/tendances",
    summary="Evolution du prix d'un carburant",
    description=(
        "Serie journaliere du prix d'un carburant, en France, dans un departement ou "
        "sur un reseau.\n\n"
        "**Ces moyennes portent sur les prix en vigueur chaque jour, pas sur les seuls "
        "prix modifies ce jour-la.** La distinction n'est pas un detail : le flux ne "
        "publie que les changements, et moyenner les changements reviendrait a ne "
        "compter que les stations qui bougent souvent leurs prix.\n\n"
        "Sont ecartes du calcul les prix atypiques, les prix perimes et les carburants "
        "en rupture. Le champ `exclus` compte les prix atypiques ecartes : un agregat "
        "doit dire sur quoi il ne porte pas.\n\n"
        "Les premiers jours d'une periode amorcee reposent sur un historique encore "
        "incomplet : leur champ `stations` est nettement plus bas, c'est a cela qu'on "
        "les reconnait."
    ),
    response_model=ReponseTendance,
)
async def tendances(
    requete: Request,
    reponse: Response,
    carburant: Annotated[
        str, Query(description=f"Un des {', '.join(CARBURANTS)}.", examples=["gazole"])
    ],
    departement: Annotated[
        str | None,
        Query(
            description="Code departement (`13`, `2A`). Absent : la France entiere.",
            examples=["13"],
        ),
    ] = None,
    reseau: Annotated[
        str | None,
        Query(
            description="`autoroute` ou `route`. Incompatible avec `departement`.",
            examples=["autoroute"],
        ),
    ] = None,
    jours: Annotated[
        int, Query(ge=1, le=JOURS_MAX, description="Profondeur de la serie.", examples=[90])
    ] = 90,
) -> ReponseTendance:
    """La serie journaliere demandee."""
    _verifier_carburant(carburant)
    if departement is not None and reseau is not None:
        raise ProblemeAPI(
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Deux decoupages demandes",
            detail=(
                "`departement` et `reseau` s'excluent : une serie porte sur un seul "
                "decoupage a la fois."
            ),
            type_=f"{BASE_TYPE}#decoupages-incompatibles",
        )
    if reseau is not None and reseau not in ("autoroute", "route"):
        raise ProblemeAPI(
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Reseau inconnu",
            detail="`reseau` accepte « autoroute » ou « route ».",
            type_=f"{BASE_TYPE}#reseau-inconnu",
        )

    if departement is not None:
        dimension, valeur = "departement", departement.upper()
    elif reseau is not None:
        dimension, valeur = "reseau", reseau
    else:
        dimension, valeur = "france", ""

    lignes = await serie(
        requete.app.state.pool,
        RechercheTendance(carburant=carburant, dimension=dimension, valeur=valeur, jours=jours),
    )
    corps = ReponseTendance(
        carburant=carburant,
        dimension=dimension,
        valeur=valeur,
        jours=jours,
        points=[
            PointSerie(
                jour=ligne["jour"],
                stations=ligne["stations"],
                exclus=ligne["exclus"],
                prix_min_eur_l=float(ligne["prix_min"]),
                prix_median_eur_l=float(ligne["prix_median"]),
                prix_moyen_eur_l=float(ligne["prix_moyen"]),
                prix_max_eur_l=float(ligne["prix_max"]),
            )
            for ligne in lignes
        ],
    )
    poser_entetes(reponse, corps, max_age=_duree_cache_tendances())
    return corps


def _en_facteur(ligne: dict[str, object]) -> FacteurEmission:
    libelle = str(ligne["nom_base"])
    if ligne["nom_attribut"]:
        libelle = f"{libelle} / {ligne['nom_attribut']}"
    return FacteurEmission(
        carburant=str(ligne["carburant"]),
        valeur_kg_co2e_par_litre=float(ligne["valeur"]),  # type: ignore[arg-type]
        unite=str(ligne["unite"]),
        libelle_ademe=libelle,
        localisation=str(ligne["localisation"]) if ligne["localisation"] else None,
        statut=str(ligne["statut"]) if ligne["statut"] else None,
        periode_validite=str(ligne["periode_validite"]) if ligne["periode_validite"] else None,
        version_base=str(ligne["version_base"]),
        url=str(ligne["url"]),
    )


@routeur.get(
    "/empreinte",
    summary="Empreinte carbone d'un plein",
    description=(
        "Multiplie un volume par le facteur d'emission du carburant, tel que publie "
        "par la Base Carbone de l'ADEME.\n\n"
        "**Le facteur est rendu avec sa provenance complete** : libelle exact de "
        "l'ADEME, perimetre, periode de validite, version du jeu et URL. Un chiffre "
        "d'empreinte carbone sans sa source ne vaut rien."
    ),
    response_model=ReponseEmpreinte,
)
async def empreinte(
    requete: Request,
    reponse: Response,
    carburant: Annotated[
        str, Query(description=f"Un des {', '.join(CARBURANTS)}.", examples=["gazole"])
    ],
    litres: Annotated[
        float, Query(gt=0, le=LITRES_MAX, description="Volume du plein.", examples=[40.0])
    ] = 40.0,
) -> ReponseEmpreinte:
    """L'empreinte d'un plein, et d'ou vient le facteur."""
    _verifier_carburant(carburant)
    lignes = await facteurs_emission(requete.app.state.pool, carburant)
    if not lignes:
        raise ProblemeAPI(
            statut=status.HTTP_503_SERVICE_UNAVAILABLE,
            titre="Facteur d'emission indisponible",
            detail=(
                "Aucun facteur d'emission n'est charge pour ce carburant. "
                "La commande `etl facteurs` n'a pas encore tourne."
            ),
            type_=f"{BASE_TYPE}#facteur-absent",
        )
    facteur = _en_facteur(lignes[0])
    corps = ReponseEmpreinte(
        carburant=carburant,
        litres=litres,
        co2_kg=round(facteur.valeur_kg_co2e_par_litre * litres, 2),
        facteur=facteur,
    )
    poser_entetes(reponse, corps, max_age=_duree_cache_tendances())
    return corps


@routeur.get(
    "/empreinte/comparaison",
    summary="Empreinte comparee des six carburants",
    description=(
        "Le meme volume, dans les six carburants, pour voir ce que change le choix du "
        "carburant. Attention : comparer litre pour litre n'est pas comparer kilometre "
        "pour kilometre -- un vehicule ne consomme pas le meme volume d'E85 que de "
        "gazole. Le champ `avertissement` le rappelle."
    ),
    response_model=ReponseComparaison,
)
async def comparaison(
    requete: Request,
    reponse: Response,
    litres: Annotated[
        float, Query(gt=0, le=LITRES_MAX, description="Volume compare.", examples=[40.0])
    ] = 40.0,
) -> ReponseComparaison:
    """Les six carburants, au meme volume."""
    lignes = await facteurs_emission(requete.app.state.pool)
    if not lignes:
        raise ProblemeAPI(
            statut=status.HTTP_503_SERVICE_UNAVAILABLE,
            titre="Facteurs d'emission indisponibles",
            detail="Aucun facteur n'est charge. La commande `etl facteurs` n'a pas tourne.",
            type_=f"{BASE_TYPE}#facteur-absent",
        )
    empreintes = [
        Empreinte(
            carburant=str(ligne["carburant"]),
            co2_kg=round(float(ligne["valeur"]) * litres, 2),
            facteur_kg_co2e_par_litre=float(ligne["valeur"]),
        )
        for ligne in lignes
    ]
    corps = ReponseComparaison(
        litres=litres,
        empreintes=sorted(empreintes, key=lambda e: e.co2_kg),
        source=_en_facteur(lignes[0]).version_base,
        # Pas de chiffre ici tant qu'il n'est pas source : la surconsommation de
        # l'E85 est reelle et connue, mais l'annoncer en pourcentage demanderait une
        # reference. Voir docs/a-verifier.md.
        avertissement=(
            "Comparaison a volume egal, pas a distance egale : pour parcourir la meme "
            "distance, un vehicule ne consomme pas le meme volume d'E85 que d'essence."
        ),
    )
    poser_entetes(reponse, corps, max_age=_duree_cache_tendances())
    return corps
