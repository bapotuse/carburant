"""Table unique de normalisation des codes carburant.

C'est la seule source de verite du projet pour les codes carburant. L'API les expose
dans son OpenAPI et sur `/v1/meta` ; le serveur MCP les recupere par l'API plutot que
de tenir une deuxieme liste (voir docs/decisions.md).

Les six carburants publies par le flux sont les seuls qui existent : Gazole, SP95,
SP95-E10, SP98, E85, GPLc. `GNV` et `Bornes electriques` apparaissent dans le flux
comme des *services*, pas comme des carburants, et n'ont pas de prix publie
(docs/reconnaissance.md, section 1.7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

type CodeCarburant = str


@dataclass(frozen=True, slots=True)
class Carburant:
    """Un carburant publie par le flux."""

    code: CodeCarburant
    """Code normalise, en minuscules, sans accent : la cle utilisee partout."""
    libelle: str
    """Libelle affichable, en francais."""
    nom_flux: str
    """Nom exact tel qu'il apparait dans l'attribut `nom` du XML amont."""
    champ_flux: str
    """Prefixe des colonnes de data.economie (`<prefixe>_prix`, `<prefixe>_maj`)."""
    token_couleur: str
    """Cle du token de couleur CSS, cote front."""
    forme: str
    """Forme de la pastille, norme EN 16942 : cercle, carre ou losange."""
    borne_min: float
    """Borne absolue basse, en euros par litre. En dessous : rejete et compte."""
    borne_max: float
    """Borne absolue haute, en euros par litre. Au dessus : rejete et compte."""


# Bornes absolues derivees de la distribution reelle du 23/11/2026
# (docs/reconnaissance.md, section 1.11). Elles rejettent les vraies erreurs de
# saisie -- par exemple un prix de SP95 saisi dans la case E85 -- sans toucher aux
# prix eleves legitimes des iles et des stations de ski.
CARBURANTS: Final[tuple[Carburant, ...]] = (
    Carburant("gazole", "Gazole", "Gazole", "gazole", "carburant-gazole", "carre", 0.80, 3.50),
    Carburant("sp95", "SP95", "SP95", "sp95", "carburant-sp95", "cercle", 0.80, 3.50),
    Carburant("e10", "SP95-E10", "E10", "e10", "carburant-e10", "cercle", 0.80, 3.50),
    Carburant("sp98", "SP98", "SP98", "sp98", "carburant-sp98", "cercle", 0.80, 3.50),
    Carburant("e85", "E85", "E85", "e85", "carburant-e85", "cercle", 0.35, 1.60),
    Carburant("gplc", "GPLc", "GPLc", "gplc", "carburant-gplc", "losange", 0.35, 2.00),
)

PAR_CODE: Final[dict[CodeCarburant, Carburant]] = {c.code: c for c in CARBURANTS}
PAR_NOM_FLUX: Final[dict[str, Carburant]] = {c.nom_flux: c for c in CARBURANTS}
CODES: Final[tuple[CodeCarburant, ...]] = tuple(c.code for c in CARBURANTS)


class CarburantInconnu(ValueError):
    """Leve quand une valeur ne correspond a aucun carburant publie."""

    def __init__(self, valeur: str) -> None:
        self.valeur = valeur
        super().__init__(f"carburant inconnu : {valeur!r}. Valeurs acceptees : {', '.join(CODES)}.")


def depuis_nom_flux(nom: str) -> Carburant:
    """Convertit le `nom` d'un element `<prix>` du XML en carburant.

    Insensible a la casse et aux espaces, parce que les archives anciennes et le flux
    actuel ne s'accordent pas toujours sur la casse.
    """
    cherche = nom.strip().casefold()
    for carburant in CARBURANTS:
        if carburant.nom_flux.casefold() == cherche:
            return carburant
    raise CarburantInconnu(nom)


def est_dans_les_bornes(code: CodeCarburant, prix: float) -> bool:
    """Un prix est-il dans les bornes absolues de son carburant ?

    Hors bornes, le prix est rejete et compte : ce n'est pas un prix.
    """
    carburant = PAR_CODE.get(code)
    if carburant is None:
        raise CarburantInconnu(code)
    return carburant.borne_min <= prix <= carburant.borne_max
