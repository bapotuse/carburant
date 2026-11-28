"""Mettre une réponse de l'API en français, et en dire les limites.

Le serveur rend deux choses à chaque appel : une **sortie structurée**, que le client
peut exploiter mécaniquement, et un **texte court**, qu'un modèle restitue à l'oral.
Les deux portent les mêmes chiffres ; le texte ajoute ce qu'un tableau ne dit pas.

Trois règles tenues ici, et aucune n'est cosmétique.

1. **Un prix n'apparaît jamais sans sa date.** C'est la règle du projet, et elle vaut
   doublement pour un assistant vocal : « l'essence est à 1,75 € » devient faux au
   bout de quelques jours, alors que « 1,75 €, relevé il y a deux heures » reste vrai
   pour toujours.
2. **Au-delà de vingt-quatre heures, le texte le dit.** Pas en caractères gras cachés
   dans une structure, mais dans la phrase, parce que c'est la phrase qui sera lue.
3. **« sp95 » ne sort jamais nu.** C'est un code d'API ; on écrit « sans plomb 95 ».
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Final

from pydantic import BaseModel, Field

from carburant_mcp.carburants import libelle
from carburant_mcp.formats import age_relatif, distance_km, euros, prix_litre

HEURES_AVANT_AVERTISSEMENT: Final = 24
"""Au-delà, le texte signale l'âge du prix.

Vingt-quatre heures n'est pas le seuil de péremption du projet (trente jours) : c'est
le seuil au-delà duquel on prévient. La différence est voulue — un prix de trois jours
reste utile et affichable, mais quelqu'un qui va rouler mérite de savoir qu'il n'a pas
été relevé ce matin.
"""


def _itineraires(latitude: float, longitude: float) -> dict[str, str]:
    """Les trois liens d'itinéraire, pour que le client ouvre celui qu'il veut.

    On ne devine pas la plateforme : un serveur MCP ne sait pas sur quel appareil son
    utilisateur se trouve, et proposer les trois coûte trois lignes de JSON.
    """
    return {
        "apple_plans": f"https://maps.apple.com/?daddr={latitude},{longitude}",
        "google_maps": (
            f"https://www.google.com/maps/dir/?api=1&destination={latitude},{longitude}"
        ),
        "waze": f"https://waze.com/ul?ll={latitude},{longitude}&navigate=yes",
    }


class StationLisible(BaseModel):
    """Une station telle qu'on la restitue : chiffres bruts et formules françaises."""

    id: int = Field(description="Identifiant officiel de la station.")
    enseigne: str | None = Field(
        default=None,
        description=(
            "Enseigne quand OpenStreetMap la connait (99,4 % des stations). Sinon la "
            "station s'identifie par son adresse : le flux officiel ne publie pas de nom."
        ),
    )
    adresse: str | None = None
    ville: str | None = None
    code_postal: str | None = None
    autoroute: bool = Field(
        default=False, description="Une station d'autoroute est structurellement plus chere."
    )

    carburant: str = Field(description="Code du carburant.")
    carburant_libelle: str = Field(description="Son nom en francais.")
    prix_eur_l: float = Field(description="Prix au litre, en euros.")
    prix_affiche: str = Field(description="Le meme prix au format francais.", examples=["1,879 €"])

    distance_km: Annotated[float, Field(ge=0)] = Field(description="Distance a vol d'oiseau.")
    distance_affichee: str = Field(examples=["2,3 km"])

    maj: dt.datetime | None = Field(default=None, description="Date du dernier changement de prix.")
    maj_affichee: str | None = Field(
        default=None, description="L'age du prix, dit comme a l'oral.", examples=["il y a 2 heures"]
    )
    prix_date_de_plus_de_24h: bool = Field(
        default=False,
        description="Vrai si le prix n'a pas ete releve depuis plus de vingt-quatre heures.",
    )

    itineraires: dict[str, str] = Field(
        default_factory=dict, description="Liens d'itineraire Apple Plans, Google Maps et Waze."
    )


def _age(maj: dt.datetime | None, maintenant: dt.datetime) -> tuple[str | None, bool]:
    """L'âge d'un prix, en français, et s'il faut prévenir."""
    if maj is None:
        return None, False
    heures = (maintenant - maj).total_seconds() / 3600
    return age_relatif(maj, reference=maintenant), heures > HEURES_AVANT_AVERTISSEMENT


def _horodatage(valeur: Any) -> dt.datetime | None:
    """Lit un horodatage de l'API, qui le rend en ISO-8601 avec son fuseau."""
    if not isinstance(valeur, str) or not valeur:
        return None
    try:
        instant = dt.datetime.fromisoformat(valeur)
    except ValueError:
        return None
    # Un instant naif viendrait d'un changement de contrat ; on le refuse plutot que
    # de lui supposer un fuseau et de se tromper d'une heure deux fois par an.
    return instant if instant.tzinfo is not None else None


def lire_station(
    station: dict[str, Any],
    prix: dict[str, Any],
    *,
    maintenant: dt.datetime,
) -> StationLisible:
    """Assemble une station et l'un de ses prix en une entrée lisible."""
    maj = _horodatage(prix.get("maj"))
    maj_affichee, vieux = _age(maj, maintenant)
    distance = float(station.get("distance_km") or station.get("distance_vol_oiseau_km") or 0.0)
    code = str(prix["carburant"])
    valeur = float(prix["prix_eur_l"])
    return StationLisible(
        id=int(station["id"]),
        enseigne=station.get("enseigne"),
        adresse=station.get("adresse"),
        ville=station.get("ville"),
        code_postal=station.get("cp"),
        autoroute=bool(station.get("autoroute", False)),
        carburant=code,
        carburant_libelle=libelle(code),
        prix_eur_l=valeur,
        prix_affiche=prix_litre(valeur),
        distance_km=distance,
        distance_affichee=distance_km(distance),
        maj=maj,
        maj_affichee=maj_affichee,
        prix_date_de_plus_de_24h=vieux,
        itineraires=_itineraires(float(station["latitude"]), float(station["longitude"])),
    )


def nommer(station: StationLisible) -> str:
    """Comment désigner une station en une poignée de mots.

    L'enseigne quand on la connaît, sinon l'adresse. Jamais l'identifiant : « 13008003 »
    ne veut rien dire pour la personne qui écoute.
    """
    morceaux = [station.enseigne] if station.enseigne else []
    if station.adresse:
        morceaux.append(station.adresse.strip())
    if station.ville:
        morceaux.append(station.ville)
    return ", ".join(m for m in morceaux if m) or f"station {station.id}"


def decrire(station: StationLisible) -> str:
    """Une phrase pour une station : prix, date, lieu, distance.

    L'ordre n'est pas indifférent. Le prix d'abord, parce que c'est la question ; la
    date juste après, parce que c'est ce qui rend le prix vrai ou faux.
    """
    phrase = f"{station.prix_affiche}"
    if station.maj_affichee:
        phrase += f" ({station.maj_affichee})"
    phrase += f" — {nommer(station)}, à {station.distance_affichee}"
    if station.autoroute:
        phrase += ", sur autoroute"
    if station.prix_date_de_plus_de_24h:
        phrase += " ⚠ prix de plus de 24 h"
    return phrase


def cout_lisible(montant: float) -> str:
    """Un coût en euros, au format français."""
    return euros(montant)
