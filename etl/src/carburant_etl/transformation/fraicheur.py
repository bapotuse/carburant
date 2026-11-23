"""Classement d'un prix selon son age.

`maj` est la date du dernier **changement** de prix, pas celle du dernier controle. Une
station qui ne bouge pas ses prix pendant dix jours affiche une `maj` vieille de dix
jours sans que la donnee soit fausse. D'ou des seuils plus larges que l'intuition.

Mesure du 23/11/2026 sur les 32 867 couples station x carburant du flux
(docs/reconnaissance.md section 1.9) : 37,9 % des prix ont moins de 24 h, 81,9 % moins
de 7 jours, 96,8 % moins de 30 jours. Le seuil initialement propose -- perime au dela
de 7 jours et exclu des recherches -- ecarterait 18 % des prix et 40 % du GPLc.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Final

from carburant_etl.fuseau import maintenant

SEUIL_FRAIS: Final = dt.timedelta(hours=48)
SEUIL_RECENT: Final = dt.timedelta(days=7)
SEUIL_ANCIEN: Final = dt.timedelta(days=30)


class Fraicheur(StrEnum):
    """Classe de fraicheur d'un prix. L'ordre va du plus frais au plus vieux."""

    FRAIS = "frais"
    """Moins de 48 h. Affiche normalement."""
    RECENT = "recent"
    """De 48 h a 7 jours. Affiche, avec sa date en mention discrete."""
    ANCIEN = "ancien"
    """De 7 a 30 jours. Avertissement visible. Conserve dans les recherches, mais
    exclu des classements et des moyennes."""
    PERIME = "perime"
    """Plus de 30 jours. Exclu des recherches ; visible sur la fiche, avec sa date."""


def classer(maj: dt.datetime, *, reference: dt.datetime | None = None) -> Fraicheur:
    """Classe un prix d'apres l'age de sa date de mise a jour.

    `reference` permet de figer l'instant present en test.
    Une `maj` dans le futur est traitee comme fraiche : c'est l'affaire du controle
    qualite `max(maj) <= now()` de la signaler, pas celle de l'affichage.
    """
    if maj.tzinfo is None:
        raise ValueError("maj naive : le fuseau doit etre explicite")
    age = (reference or maintenant()) - maj
    if age <= SEUIL_FRAIS:
        return Fraicheur.FRAIS
    if age <= SEUIL_RECENT:
        return Fraicheur.RECENT
    if age <= SEUIL_ANCIEN:
        return Fraicheur.ANCIEN
    return Fraicheur.PERIME


def utilisable_en_recherche(fraicheur: Fraicheur) -> bool:
    """Ce prix peut-il etre propose dans une recherche de station ?"""
    return fraicheur is not Fraicheur.PERIME


def utilisable_en_classement(fraicheur: Fraicheur) -> bool:
    """Ce prix peut-il entrer dans un classement ou une moyenne ?

    Un prix ancien reste une information utile pour l'utilisateur qui cherche une
    station, mais il fausserait une moyenne departementale ou un palmares.
    """
    return fraicheur in (Fraicheur.FRAIS, Fraicheur.RECENT)
