"""Schémas de `/v1/stations/meilleure`.

La réponse est bavarde là où ça compte : elle ne donne pas un classement opaque
mais le **détail du calcul** pour chaque station — le prix du plein, le coût du
détour, la distance retenue — et les hypothèses sous lesquelles ce calcul tient.
Un chiffre qu'on ne peut pas refaire soi-même n'a pas sa place devant quelqu'un qui
va faire dix kilomètres sur la foi de ce qu'on lui dit.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from pydantic import BaseModel, Field

from carburant_api.schemas.station import Fraicheur


class Hypotheses(BaseModel):
    """Ce que le calcul suppose, dit explicitement."""

    aller_retour: bool = Field(
        default=True,
        description=(
            "Le detour est compte a l'aller **et** au retour. Vrai pour qui fait un "
            "detour expres, faux pour qui fait le plein sur sa route."
        ),
    )
    facteur_detour: float = Field(
        description=(
            "Rapport applique entre distance a vol d'oiseau et distance routiere "
            "estimee. Valeur de depart, non encore calibree contre un service "
            "d'itineraire."
        ),
        examples=[1.3],
    )
    marge_autonomie: float = Field(
        description=(
            "Part de l'autonomie annoncee qu'on s'autorise a consommer. "
            "L'autonomie d'un tableau de bord est optimiste."
        ),
        examples=[0.8],
    )
    litres: float = Field(description="Volume du plein retenu, en litres.", examples=[40.0])
    consommation_l_100km: float = Field(
        description="Consommation retenue, en litres aux 100 km.", examples=[7.0]
    )
    prix_du_trajet: str = Field(
        default=(
            "Le carburant brule pendant le trajet est valorise au prix de la station "
            "visee. C'est une approximation : il vient en realite du reservoir, "
            "achete ailleurs."
        ),
        description="Comment le carburant du detour est valorise.",
    )


class StationEvaluee(BaseModel):
    """Une station atteignable, avec le detail de son cout."""

    id: int = Field(description="Identifiant officiel de la station.", examples=[13008003])
    adresse: str | None = Field(default=None, examples=["32 boulevard Schloesing"])
    ville: str | None = Field(default=None, examples=["Marseille"])
    cp: str | None = Field(default=None, examples=["13010"])
    enseigne: str | None = Field(
        default=None,
        description="Enseigne, quand OpenStreetMap la connait. Sinon la station s'identifie par son adresse.",
        examples=["TotalEnergies"],
    )
    autoroute: bool = Field(default=False, examples=[False])
    latitude: float = Field(examples=[43.2726])
    longitude: float = Field(examples=[5.3846])

    distance_vol_oiseau_km: Annotated[float, Field(ge=0)] = Field(
        description="Distance geodesique depuis la position donnee.", examples=[2.3]
    )
    distance_routiere_km: Annotated[float, Field(ge=0)] = Field(
        description="Distance routiere **estimee** : la precedente, multipliee par le facteur de detour.",
        examples=[2.99],
    )

    prix_eur_l: Annotated[float, Field(gt=0)] = Field(examples=[1.879])
    maj: dt.datetime | None = Field(
        default=None,
        description="Date du dernier changement de ce prix.",
        examples=["2026-11-26T08:12:00Z"],
    )
    fraicheur: Fraicheur | None = Field(default=None, examples=["frais"])

    cout_plein_eur: float = Field(description="prix x litres.", examples=[75.16])
    cout_detour_eur: float = Field(
        description="Carburant brule pour l'aller-retour, valorise au prix de la station.",
        examples=[0.79],
    )
    cout_reel_eur: float = Field(
        description="La somme des deux. C'est sur ce chiffre que le classement se fait.",
        examples=[75.95],
    )


class ReponseMeilleure(BaseModel):
    """Le classement par cout reel, et de quoi le verifier."""

    meilleure: StationEvaluee | None = Field(
        default=None,
        description="La station au cout reel le plus bas. Absente si aucune n'est atteignable.",
    )
    la_plus_proche: StationEvaluee | None = Field(
        default=None,
        description=(
            "La station atteignable la plus proche : ce que ferait quelqu'un qui ne "
            "calcule pas. Sert de reference a l'economie."
        ),
    )
    economie_eur: float = Field(
        default=0.0,
        description=(
            "Ce qu'on gagne a aller a la meilleure plutot qu'a la plus proche. "
            "Jamais negatif : si la plus proche est la meilleure, il n'y a rien a gagner."
        ),
        examples=[1.42],
    )
    stations: list[StationEvaluee] = Field(
        default_factory=list, description="Les meilleures candidates, par cout reel croissant."
    )
    atteignables: int = Field(
        default=0, description="Nombre de stations atteignables trouvees.", examples=[12]
    )
    avertissement: str | None = Field(
        default=None,
        description=(
            "Rempli quand la reponse demande une precaution : aucune station "
            "atteignable, autonomie trop faible, position hors de France."
        ),
        examples=["Aucune station atteignable avec 20 km d'autonomie."],
    )
    hypotheses: Hypotheses
