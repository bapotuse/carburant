"""Les six carburants, et les mots que les gens emploient pour les désigner.

Un assistant reçoit « du diesel », « du sans plomb », « du E10 », « du GPL ». L'API,
elle, ne connaît que six codes. C'est ici que la traduction se fait, et c'est elle qui
décide si une demande est comprise ou refusée.

**Pourquoi cette table n'est pas partagée avec l'ETL**, qui normalise lui aussi les
noms de carburants : ce paquet s'installe seul depuis PyPI, sans la base ni l'ETL.
Partager la table demanderait de publier un paquet commun pour une quinzaine de
lignes de données. Ce ne sont d'ailleurs pas les mêmes données : l'ETL traduit les
libellés **du flux officiel**, qui sont fixes et au nombre de six ; ici on traduit ce
qu'un humain dit, ce qui est ouvert et sans fin. Un test vérifie que les six codes
sont bien les mêmes de part et d'autre, car c'est la seule chose qui doit coïncider.

**Une demande ambiguë est refusée, pas devinée.** « Super » peut désigner le SP95 ou
le SP98 ; deviner afficherait un prix faux sans le dire. Le refus nomme les candidats,
ce qu'un modèle de langage sait exploiter pour reformuler sa question.
"""

from __future__ import annotations

import unicodedata
from typing import Final

CODES: Final = ("gazole", "sp95", "e10", "sp98", "e85", "gplc")
"""Les six carburants publiés par le flux officiel, dans l'ordre d'affichage."""

LIBELLES: Final[dict[str, str]] = {
    "gazole": "gazole",
    "sp95": "sans plomb 95",
    "e10": "sans plomb 95-E10",
    "sp98": "sans plomb 98",
    "e85": "superéthanol E85",
    "gplc": "GPL carburant",
}
"""Le nom à écrire dans une réponse. « sp95 » est un code, pas du français."""

_SYNONYMES: Final[dict[str, str]] = {
    # Gazole. « b7 » est la mention réglementaire affichée sur les pompes françaises.
    "gazole": "gazole",
    "gasoil": "gazole",
    "gazoil": "gazole",
    "diesel": "gazole",
    "b7": "gazole",
    "go": "gazole",
    "gazole routier": "gazole",
    # SP95
    "sp95": "sp95",
    "sp 95": "sp95",
    "95": "sp95",
    "sans plomb 95": "sp95",
    "sans plomb95": "sp95",
    "essence 95": "sp95",
    "super 95": "sp95",
    "e5": "sp95",
    # SP95-E10. « e10 » est la mention réglementaire.
    "e10": "e10",
    "e 10": "e10",
    "sp95 e10": "e10",
    "sp95e10": "e10",
    "95 e10": "e10",
    "sans plomb 95 e10": "e10",
    "ethanol 10": "e10",
    # SP98
    "sp98": "sp98",
    "sp 98": "sp98",
    "98": "sp98",
    "sans plomb 98": "sp98",
    "sans plomb98": "sp98",
    "essence 98": "sp98",
    "super 98": "sp98",
    # E85
    "e85": "e85",
    "e 85": "e85",
    "superethanol": "e85",
    "superethanol e85": "e85",
    "super ethanol": "e85",
    "bioethanol": "e85",
    "ethanol": "e85",
    "ethanol 85": "e85",
    # GPL
    "gplc": "gplc",
    "gpl": "gplc",
    "gpl c": "gplc",
    "gplc carburant": "gplc",
    "gpl carburant": "gplc",
    "lpg": "gplc",
    "gaz": "gplc",
    "gaz de petrole liquefie": "gplc",
}

_AMBIGUS: Final[dict[str, tuple[str, ...]]] = {
    # « Super » a désigné le 98 plombé, puis le 95 par glissement d'usage. Les deux
    # lectures se défendent, donc on demande laquelle.
    "super": ("sp95", "sp98"),
    "essence": ("sp95", "e10", "sp98", "e85"),
    "sans plomb": ("sp95", "e10", "sp98"),
    "sp": ("sp95", "sp98"),
}
"""Termes qu'on refuse de trancher. La réponse nomme les candidats."""


class CarburantInconnu(ValueError):
    """Le terme ne désigne aucun carburant connu."""


class CarburantAmbigu(ValueError):
    """Le terme désigne plusieurs carburants ; on ne choisit pas à la place du lecteur."""

    def __init__(self, terme: str, candidats: tuple[str, ...]) -> None:
        self.terme = terme
        self.candidats = candidats
        lisibles = ", ".join(f"« {LIBELLES[code]} » ({code})" for code in candidats)
        super().__init__(
            f"« {terme} » peut designer plusieurs carburants : {lisibles}. "
            "Precise lequel plutot que de laisser deviner : un prix faux ne se voit pas."
        )


def _aplatir(texte: str) -> str:
    """Minuscules, sans accents, espaces réduits, ponctuation neutralisée.

    « Sans-Plomb 95 », « sans plomb 95 » et « SANS   PLOMB 95 » doivent se rejoindre.
    Les tirets et les points deviennent des espaces plutôt que de disparaître, sinon
    « sp-95 » et « sp95 » donneraient deux clés différentes selon le sens du tiret.
    """
    sans_accents = "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texte.lower())
        if unicodedata.category(caractere) != "Mn"
    )
    remplace = "".join(caractere if caractere.isalnum() else " " for caractere in sans_accents)
    return " ".join(remplace.split())


def normaliser(terme: str) -> str:
    """Le code du carburant désigné par `terme`.

    Lève `CarburantAmbigu` si plusieurs carburants conviennent, `CarburantInconnu`
    sinon. Les deux messages sont écrits pour être relayés tels quels à un modèle de
    langage : ils disent quoi faire, pas seulement ce qui ne va pas.
    """
    cle = _aplatir(terme)
    if not cle:
        raise CarburantInconnu(
            "Aucun carburant indique. Valeurs acceptees : " + ", ".join(CODES) + "."
        )
    if cle in _SYNONYMES:
        return _SYNONYMES[cle]
    # L'ambiguïté est testée après les synonymes : « sans plomb 95 » est précis,
    # « sans plomb » ne l'est pas, et le plus précis doit gagner.
    if cle in _AMBIGUS:
        raise CarburantAmbigu(terme, _AMBIGUS[cle])
    raise CarburantInconnu(
        f"« {terme} » n'est pas un carburant reconnu. Valeurs acceptees : "
        + ", ".join(CODES)
        + ". Les synonymes courants marchent aussi : diesel, sans plomb 95, E10, GPL."
    )


def libelle(code: str) -> str:
    """Le nom lisible d'un code, pour l'écrire dans une réponse."""
    return LIBELLES.get(code, code)
