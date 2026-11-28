"""Du texte libre vers un point sur la carte.

Un assistant reçoit « je suis au Prado à Marseille », pas une latitude. Le géocodage
passe par `/v1/geocode`, qui applique déjà la règle d'ambiguïté chiffrée du projet et
rend ses candidats avec leur score.

**Le cas intéressant est l'ambiguïté, et il est fréquent.** L'avenue du Prado existe
en 13006 et en 13008, à 1,2 km l'une de l'autre, avec des scores quasi identiques : il
n'y a pas de bon candidat à devenir. Dans ce cas on ne choisit pas — on rend la liste
et on le dit. Un modèle de langage sait alors poser la question à l'utilisateur, ce
qui est exactement la bonne issue ; choisir à sa place donnerait les prix d'un autre
quartier sans que personne ne s'en aperçoive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from carburant_mcp.client import ClientCarburant


@dataclass(frozen=True, slots=True)
class Lieu:
    """Un lieu identifié sans ambiguïté."""

    libelle: str
    latitude: float
    longitude: float
    ville: str | None
    code_postal: str | None
    score: float


class LieuAmbigu(Exception):
    """Plusieurs lieux conviennent. On rend la liste au lieu de choisir.

    Ce n'est pas une erreur de l'utilisateur : c'est une propriété de l'adresse qu'il
    a donnée. Le message et la liste sont faits pour être relayés.
    """

    def __init__(self, requete: str, candidats: list[dict[str, Any]], raison: str | None) -> None:
        self.requete = requete
        self.candidats = candidats
        self.raison = raison
        apercu = " ; ".join(
            f"{candidat['libelle']}"
            + (f" ({candidat['code_postal']})" if candidat.get("code_postal") else "")
            for candidat in candidats[:5]
        )
        super().__init__(
            f"« {requete} » peut designer plusieurs endroits : {apercu}. "
            "Demande lequel avant de donner des prix : deux candidats peuvent etre a "
            "un kilometre l'un de l'autre et n'avoir aucune station en commun."
        )


class LieuIntrouvable(Exception):
    """Le géocodeur ne connaît pas ce lieu."""

    def __init__(self, requete: str) -> None:
        self.requete = requete
        super().__init__(
            f"« {requete} » est introuvable. Precise la ville ou le code postal, par "
            "exemple « 40 avenue du Prado, 13006 Marseille » ou « 13008 ». Seules la "
            "France metropolitaine et la Corse sont couvertes."
        )


async def geocoder(client: ClientCarburant, requete: str) -> Lieu:
    """Le point désigné par `requete`, ou une exception qui dit quoi faire.

    Les trois issues sont distinctes à dessein : un lieu, une ambiguïté à lever, ou
    une absence. Les confondre dans un `None` obligerait l'appelant à redemander à
    l'API pour savoir laquelle.
    """
    texte = requete.strip()
    if not texte:
        raise LieuIntrouvable(requete)

    reponse = await client.obtenir("/geocode", q=texte)
    candidats = reponse.get("candidats") or []
    if not candidats:
        raise LieuIntrouvable(texte)
    if reponse.get("ambigu"):
        raise LieuAmbigu(texte, candidats, reponse.get("raison"))

    premier = candidats[0]
    return Lieu(
        libelle=str(premier["libelle"]),
        latitude=float(premier["latitude"]),
        longitude=float(premier["longitude"]),
        ville=premier.get("ville"),
        code_postal=premier.get("code_postal"),
        score=float(premier["score"]),
    )
