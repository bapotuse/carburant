"""Schemas des series de prix et de l'empreinte carbone."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from pydantic import BaseModel, Field


class PointSerie(BaseModel):
    """Un jour d'une serie de prix."""

    jour: dt.date = Field(examples=["2026-11-25"])
    stations: int = Field(
        description=(
            "Nombre de prix retenus ce jour-la. Nettement plus bas sur les premiers "
            "jours d'une periode amorcee : l'historique n'y est pas encore complet."
        ),
        examples=[8742],
    )
    exclus: int = Field(
        description="Prix atypiques ecartes du calcul mais comptes.", examples=[106]
    )
    prix_min_eur_l: float = Field(examples=[1.629])
    prix_median_eur_l: float = Field(examples=[1.879])
    prix_moyen_eur_l: float = Field(examples=[1.884])
    prix_max_eur_l: float = Field(examples=[2.319])


class ReponseTendance(BaseModel):
    """Une serie journaliere, et ce sur quoi elle porte."""

    carburant: str = Field(examples=["gazole"])
    dimension: str = Field(
        description="`france`, `departement` ou `reseau`.", examples=["departement"]
    )
    valeur: str = Field(
        description="Le decoupage : vide pour la France, un code de departement, ou autoroute/route.",
        examples=["13"],
    )
    jours: int = Field(description="Profondeur demandee.", examples=[90])
    points: list[PointSerie] = Field(default_factory=list)


class FacteurEmission(BaseModel):
    """Un facteur d'emission, avec sa provenance complete.

    Sans provenance, un chiffre d'empreinte carbone n'est pas verifiable : c'est
    l'ADEME qui le publie, pas nous.
    """

    carburant: str = Field(examples=["gazole"])
    valeur_kg_co2e_par_litre: Annotated[float, Field(gt=0)] = Field(examples=[3.1])
    unite: str = Field(examples=["kgCO2e/litre"])
    libelle_ademe: str = Field(
        description="Libelle exact publie par l'ADEME, recopie sans retouche.",
        examples=["Gazole routier / B7"],
    )
    localisation: str | None = Field(default=None, examples=["France continentale"])
    statut: str | None = Field(default=None, examples=["Valide générique"])
    periode_validite: str | None = Field(default=None, examples=["déc-20"])
    version_base: str = Field(
        description="Date de derniere modification du jeu ADEME : la Base Carbone n'expose pas de numero de version.",
        examples=["2026-06-30T10:17:08.470Z"],
    )
    url: str = Field(
        examples=["https://data.ademe.fr/data-fair/api/v1/datasets/base-carboner/lines?..."]
    )


class ReponseEmpreinte(BaseModel):
    """L'empreinte d'un plein, et d'ou vient le facteur."""

    carburant: str = Field(examples=["gazole"])
    litres: float = Field(examples=[40.0])
    co2_kg: float = Field(description="litres x facteur.", examples=[124.0])
    facteur: FacteurEmission


class Empreinte(BaseModel):
    """L'empreinte d'un carburant pour le volume compare."""

    carburant: str = Field(examples=["e85"])
    co2_kg: float = Field(examples=[44.4])
    facteur_kg_co2e_par_litre: float = Field(examples=[1.11])


class ReponseComparaison(BaseModel):
    """Les six carburants au meme volume, du moins emetteur au plus emetteur."""

    litres: float = Field(examples=[40.0])
    empreintes: list[Empreinte] = Field(default_factory=list)
    source: str = Field(
        description="Version du jeu ADEME dont sont tires les facteurs.",
        examples=["2026-06-30T10:17:08.470Z"],
    )
    avertissement: str = Field(
        description="Ce que la comparaison ne dit pas.",
        examples=["Comparaison a volume egal, pas a distance egale."],
    )
