"""Schemas de reponse pour les stations.

Deux regles tenues partout :

- **l'unite est dans le nom du champ** (`prix_eur_l`, `distance_km`) : un client qui
  lit l'OpenAPI ne doit jamais avoir a deviner si une distance est en metres ou en
  kilometres ;
- **un prix n'existe jamais sans sa date**. `PrixCarburant` porte les deux, plus sa
  classe de fraicheur. Il est impossible de construire l'un sans l'autre.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Fraicheur(StrEnum):
    """Age d'un prix, en quatre classes.

    `maj` est la date du dernier **changement** de prix, pas du dernier controle :
    une station qui ne bouge pas ses prix pendant dix jours n'est pas fausse pour
    autant. Seuils mesures, voir `docs/reconnaissance.md` section 1.9.
    """

    FRAIS = "frais"
    RECENT = "recent"
    ANCIEN = "ancien"
    PERIME = "perime"


class Rupture(BaseModel):
    """Un carburant indisponible dans cette station."""

    type: Literal["temporaire", "definitive"] = Field(
        description=(
            "`definitive` veut dire que la station ne vend pas ce carburant -- ce "
            "n'est pas une panne. C'est ainsi que la source declare une absence."
        ),
        examples=["definitive"],
    )
    debut: dt.datetime | None = Field(
        default=None, description="Debut declare de la rupture, en UTC."
    )


class PrixCarburant(BaseModel):
    """Le prix d'un carburant dans une station, avec sa date et sa fraicheur."""

    carburant: str = Field(
        description="Code normalise du carburant.",
        examples=["gazole"],
    )
    prix_eur_l: Annotated[float, Field(gt=0)] | None = Field(
        default=None,
        description="Prix en euros par litre. `null` si le carburant est en rupture.",
        examples=[1.879],
    )
    maj: dt.datetime | None = Field(
        default=None,
        description=(
            "Instant du dernier **changement** de prix, en UTC. Jamais `null` quand "
            "`prix_eur_l` est renseigne : un prix sans date ne doit pas s'afficher."
        ),
        examples=["2026-11-23T16:00:00Z"],
    )
    fraicheur: Fraicheur | None = Field(
        default=None,
        description=(
            "`frais` (<= 48 h), `recent` (<= 7 j), `ancien` (<= 30 j, affiche avec un "
            "avertissement et exclu des classements), `perime` (> 30 j)."
        ),
        examples=["frais"],
    )
    rupture: Rupture | None = Field(
        default=None, description="Renseigne si le carburant est declare indisponible."
    )


class StationProche(BaseModel):
    """Une station trouvee autour d'un point."""

    id: int = Field(description="Identifiant officiel de la station.", examples=[13008003])
    adresse: str | None = Field(default=None, examples=["32 boulevard Schloesing"])
    ville: str | None = Field(default=None, examples=["Marseille"])
    cp: str | None = Field(default=None, examples=["13010"])
    departement: str | None = Field(default=None, examples=["Bouches-du-Rhône"])
    code_departement: str | None = Field(default=None, examples=["13"])
    autoroute: bool = Field(
        description="Vrai si la station est sur autoroute. 4,4 % des stations.",
        examples=[False],
    )
    latitude: float = Field(examples=[43.2726])
    longitude: float = Field(examples=[5.3846])
    distance_km: Annotated[float, Field(ge=0)] = Field(
        description="Distance a vol d'oiseau depuis le point demande, en kilometres.",
        examples=[1.3],
    )
    prix: list[PrixCarburant] = Field(
        description=(
            "Les prix connus de cette station. Quand la recherche porte sur un "
            "carburant, la liste n'en contient qu'un."
        )
    )

    @property
    def enseigne(self) -> None:
        """Le flux officiel ne contient ni nom ni enseigne de station.

        Le rapprochement avec OpenStreetMap arrive au Jalon 2. D'ici la, une station
        s'identifie par son adresse et sa ville, et on ne l'invente pas.
        """
        return None


class ReponseStationsProches(BaseModel):
    """Resultat d'une recherche de stations autour d'un point."""

    stations: list[StationProche]
    total: int = Field(description="Nombre de stations trouvees avant pagination.", examples=[57])
    rayon_km: float = Field(description="Rayon effectivement applique.", examples=[10.0])
    carburant: str | None = Field(
        default=None, description="Carburant demande, s'il y en avait un."
    )
    tri: str = Field(description="Critere de tri applique.", examples=["prix"])
    derniere_collecte: dt.datetime | None = Field(
        default=None,
        description=(
            "Instant de la derniere collecte reussie. C'est la fraicheur de "
            "l'ensemble des donnees, a distinguer de celle de chaque prix."
        ),
    )


class Enseigne(BaseModel):
    """L'enseigne d'une station, avec la facon dont elle a ete trouvee.

    Le flux officiel ne contient ni nom ni enseigne : celles-ci viennent
    d'OpenStreetMap, sous licence ODbL. La provenance est rendue avec la valeur pour
    que l'affichage puisse en tenir compte -- un rapprochement geographique merite
    plus de prudence qu'une correspondance d'identifiant.
    """

    nom: str = Field(examples=["TotalEnergies"])
    source: str = Field(
        description=(
            "`osm-reference` quand OpenStreetMap portait l identifiant officiel de la "
            "station, `osm-spatial` quand le rapprochement est geographique."
        ),
        examples=["osm-reference"],
    )
    score: float | None = Field(
        default=None,
        description="1,0 pour un rapprochement par identifiant ; degrade selon la distance sinon.",
        examples=[1.0],
    )
    objet_osm: str | None = Field(
        default=None,
        description="Objet OpenStreetMap rapproche, pour pouvoir verifier.",
        examples=["node/144574"],
    )


class FicheStation(BaseModel):
    """Tout ce qu'on sait d'une station.

    Contrairement a une recherche, une fiche **ne cache rien** : elle montre aussi
    les prix perimes et les carburants en rupture, avec leur date et leur etat. Un
    prix de deux mois n'est pas une raison de faire comme s'il n'existait pas ; c'est
    une raison de le dater.
    """

    id: int = Field(examples=[13008003])
    adresse: str | None = Field(default=None, examples=["32 boulevard Schloesing"])
    ville: str | None = Field(default=None, examples=["Marseille"])
    cp: str | None = Field(default=None, examples=["13010"])
    departement: str | None = Field(default=None, examples=["Bouches-du-Rhône"])
    code_departement: str | None = Field(default=None, examples=["13"])
    region: str | None = Field(default=None, examples=["Provence-Alpes-Côte d'Azur"])
    autoroute: bool = Field(default=False, examples=[False])
    latitude: float = Field(examples=[43.2726])
    longitude: float = Field(examples=[5.3846])
    enseigne: Enseigne | None = Field(
        default=None, description="Absente quand OpenStreetMap ne connait pas cette station."
    )
    services: list[str] = Field(default_factory=list, examples=[["Automate CB 24/24"]])
    horaires: dict[str, Any] | None = Field(
        default=None, description="Horaires normalises tels que publies par le flux."
    )
    prix: list[PrixCarburant] = Field(
        default_factory=list,
        description="Tous les carburants connus, perimes et ruptures compris.",
    )
    premiere_vue: dt.datetime = Field(
        description="Premiere fois que cette station apparait dans nos donnees."
    )
    derniere_vue: dt.datetime = Field(description="Derniere collecte ou elle etait presente.")
    active: bool = Field(
        description="Fausse quand la station a disparu du flux. Elle n'est jamais supprimee.",
        examples=[True],
    )


class ChangementPrix(BaseModel):
    """Un changement de prix, tel que la source l'a publie."""

    carburant: str = Field(examples=["gazole"])
    prix_eur_l: float = Field(examples=[1.879])
    maj: dt.datetime = Field(examples=["2026-11-25T08:12:00Z"])


class ReponseHistorique(BaseModel):
    """L'historique des prix d'une station.

    Le grain etant « un changement de prix », cet historique est exactement ce que la
    source a publie : aucun echantillonnage, aucun lissage.
    """

    station_id: int = Field(examples=[13008003])
    carburant: str | None = Field(default=None, examples=["gazole"])
    depuis: dt.datetime
    changements: list[ChangementPrix] = Field(default_factory=list)
    total: int = Field(description="Nombre de changements renvoyes.", examples=[42])
