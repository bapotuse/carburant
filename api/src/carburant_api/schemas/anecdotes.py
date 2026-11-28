"""Schémas de `/v1/anecdotes/du-jour`.

Pas de phrase rédigée dans ces schémas : des chiffres, leur contexte et de quoi les
vérifier. Le site les met en français avec `Intl`, le serveur MCP avec ses
formateurs testés — c'est la convention du projet, et elle évite d'avoir la même
phrase écrite à deux endroits.

Ce que ces schémas rendent impossible à cacher : **une anecdote sous son seuil ne
sort pas un chiffre approximatif, elle sort dans `indisponibles` avec sa raison et
sa mesure.** Un lecteur de l'OpenAPI voit donc les quatre anecdotes, les seuils, et
celles que les données du jour ne permettent pas.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from pydantic import BaseModel, Field


class StationBorne(BaseModel):
    """Une des deux bornes de l'écart du jour."""

    station_id: int = Field(examples=[13008003])
    ville: str | None = Field(default=None, examples=["Marseille"])
    cp: str | None = Field(default=None, examples=["13008"])
    code_departement: str | None = Field(default=None, examples=["13"])
    autoroute: bool = Field(
        default=False,
        description="Une borne sur autoroute n'a pas la meme signification qu'une borne en ville.",
        examples=[False],
    )
    prix_eur_l: float = Field(examples=[1.699])
    maj: dt.datetime | None = Field(default=None, examples=["2026-11-26T08:12:00Z"])


class EcartDuJour(BaseModel):
    """L'écart entre la station la moins chère et la plus chère de France."""

    stations: int = Field(
        description="Stations retenues : prix frais ou recent, hors rupture et hors prix atypique.",
        examples=[9432],
    )
    prix_min_eur_l: float = Field(examples=[1.549])
    prix_max_eur_l: float = Field(examples=[2.299])
    ecart_eur_l: float = Field(
        description="La difference entre les deux. C'est le chiffre de l'anecdote.",
        examples=[0.75],
    )
    moins_chere: StationBorne
    plus_chere: StationBorne


class DepartementMoinsCher(BaseModel):
    """Le département le moins cher sur les sept derniers jours calculés."""

    code_departement: str = Field(examples=["46"])
    prix_median_eur_l: float = Field(
        description="Moyenne des medianes journalieres du departement sur la fenetre.",
        examples=[1.812],
    )
    prix_national_eur_l: float | None = Field(default=None, examples=[1.862])
    ecart_au_national_eur_l: float | None = Field(
        default=None,
        description="Negatif : c'est ce qui fait de ce departement le moins cher.",
        examples=[-0.05],
    )
    stations: int = Field(
        description="Le plus petit effectif journalier du departement sur la fenetre.",
        examples=[34],
    )
    jours: int = Field(description="Jours d'agregat trouves sur les sept.", examples=[7])
    jour_fin: dt.date = Field(
        description="Dernier jour de la fenetre. La fenetre est calee sur le dernier "
        "agregat calcule, pas sur aujourd'hui : si la collecte date d'hier, "
        "une fenetre calee sur aujourd'hui perdrait un jour pour rien.",
        examples=["2026-11-26"],
    )
    departements_compares: int = Field(
        description="Departements ayant atteint les deux seuils, donc reellement compares.",
        examples=[96],
    )


class SurcoutAutoroute(BaseModel):
    """Le surcoût d'un plein de 50 L pris sur autoroute."""

    prix_autoroute_eur_l: float = Field(examples=[2.089])
    prix_route_eur_l: float = Field(examples=[1.862])
    ecart_eur_l: float = Field(examples=[0.227])
    litres: int = Field(
        description="Le plein de reference, fixe par la spec. Unite de comparaison, "
        "pas une moyenne francaise mesuree.",
        examples=[50],
    )
    surcout_eur: float = Field(description="ecart x litres.", examples=[11.35])
    stations_autoroute: int = Field(examples=[412])
    stations_route: int = Field(examples=[9020])
    jour: dt.date = Field(examples=["2026-11-26"])


class EcartJourSemaine(BaseModel):
    """L'écart moyen d'un jour de la semaine à sa propre semaine."""

    jour_semaine: Annotated[int, Field(ge=1, le=7)] = Field(
        description="Norme ISO-8601 : 1 = lundi, 7 = dimanche.", examples=[2]
    )
    ecart_eur_l: float = Field(
        description="Negatif : ce jour-la est moins cher que la moyenne de sa semaine.",
        examples=[-0.0043],
    )


class JourSemaineMoinsCher(BaseModel):
    """Le jour de la semaine historiquement le moins cher."""

    jour_semaine: Annotated[int, Field(ge=1, le=7)] = Field(
        description="Norme ISO-8601 : 1 = lundi, 7 = dimanche.", examples=[2]
    )
    ecart_eur_l: float = Field(examples=[-0.0043])
    semaines: int = Field(
        description="Semaines d'observation pour le jour le moins bien pourvu.", examples=[921]
    )
    classement: list[EcartJourSemaine] = Field(
        description="Les sept jours, du moins cher au plus cher."
    )
    methode: str = Field(
        description="Comment la tendance de fond a ete retiree. Sans ce retrait, le "
        "resultat mesurerait la hausse des prix sur seize ans."
    )


class AnecdoteIndisponible(BaseModel):
    """Une anecdote que les données du jour ne permettent pas de calculer."""

    cle: str = Field(examples=["jour_semaine_moins_cher"])
    raison: str = Field(
        description="Le seuil, en clair.",
        examples=["Il faut 52 semaines d'historique pour chacun des sept jours."],
    )
    mesure: str = Field(
        description="Ce qu'on a reellement, pour que le seuil soit verifiable.",
        examples=["1 jour de la semaine couvert, 0 semaine pour le moins bien pourvu"],
    )


class ReponseAnecdotes(BaseModel):
    """Les anecdotes calculables aujourd'hui, et celles qui ne le sont pas."""

    carburant: str = Field(examples=["gazole"])
    calcule_le: dt.datetime = Field(
        description="Instant du calcul. Une anecdote s'affiche toujours avec sa date.",
        examples=["2026-11-26T19:05:00Z"],
    )
    ecart_du_jour: EcartDuJour | None = None
    departement_moins_cher: DepartementMoinsCher | None = None
    surcout_autoroute: SurcoutAutoroute | None = None
    jour_semaine_moins_cher: JourSemaineMoinsCher | None = None
    indisponibles: list[AnecdoteIndisponible] = Field(
        default_factory=list,
        description=(
            "Les anecdotes sous leur seuil, avec leur raison. Elles sont declarees "
            "plutot que passees sous silence : un seuil non atteint est une information, pas un oubli."
        ),
    )
