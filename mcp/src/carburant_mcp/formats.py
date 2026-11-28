"""Formats francais pour les reponses du serveur MCP.

Le front utilise `Intl` en `fr-FR`. Cote Python, il n'y a pas d'equivalent portable --
`locale` depend des locales installees dans le conteneur, ce qui en fait une source de
bogues silencieux. Ces helpers n'ont donc aucune dependance et sont testes.

Trois regles typographiques francaises sont respectees :

- la virgule decimale ;
- l'**espace insecable etroit** (U+202F) entre un nombre et son unite, et comme
  separateur des milliers, conformement a l'usage de l'Imprimerie nationale ;
- les mois abreges avec un point, sauf juin et juillet qui ne s'abregent pas.
"""

from __future__ import annotations

import datetime as dt
from typing import Final
from zoneinfo import ZoneInfo

PARIS: Final = ZoneInfo("Europe/Paris")

INSECABLE_ETROITE: Final = "\u202f"
"""Espace fine insecable : entre un nombre et son unite, et entre les milliers."""

MOIS_ABREGES: Final = (
    "janv.",
    "fevr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "aout",
    "sept.",
    "oct.",
    "nov.",
    "dec.",
)
"""Mois abreges. « mars », « mai », « juin » ne s'abregent pas ; « aout » non plus."""


def _grouper_milliers(entier: str) -> str:
    """Groupe les chiffres par trois avec une espace fine insecable."""
    signe, chiffres = ("-", entier[1:]) if entier.startswith("-") else ("", entier)
    morceaux: list[str] = []
    while len(chiffres) > 3:
        morceaux.insert(0, chiffres[-3:])
        chiffres = chiffres[:-3]
    morceaux.insert(0, chiffres)
    return signe + INSECABLE_ETROITE.join(morceaux)


def nombre(valeur: float, decimales: int = 2) -> str:
    """Formate un nombre a la francaise : virgule decimale, milliers groupes.

    >>> nombre(1234.5)
    '1 234,50'
    >>> nombre(0.869, 3)
    '0,869'
    """
    texte = f"{valeur:.{decimales}f}"
    entier, _, fraction = texte.partition(".")
    groupe = _grouper_milliers(entier)
    return f"{groupe},{fraction}" if fraction else groupe


def prix_litre(prix_eur_l: float) -> str:
    """Un prix au litre, tel qu'il s'affiche en station : trois decimales.

    >>> prix_litre(1.879)
    '1,879 €/L'
    """
    return f"{nombre(prix_eur_l, 3)}{INSECABLE_ETROITE}€/L"


def euros(montant: float) -> str:
    """Un montant en euros, deux decimales.

    >>> euros(93.95)
    '93,95 €'
    """
    return f"{nombre(montant, 2)}{INSECABLE_ETROITE}€"


def litres(volume: float) -> str:
    """Un volume en litres.

    >>> litres(50)
    '50 L'
    """
    decimales = 0 if float(volume).is_integer() else 1
    return f"{nombre(volume, decimales)}{INSECABLE_ETROITE}L"


def distance_km(km: float) -> str:
    """Une distance. En dessous du kilometre, on parle en metres.

    >>> distance_km(2.4)
    '2,4 km'
    >>> distance_km(0.35)
    '350 m'
    """
    if km < 1:
        return f"{round(km * 1000):d}{INSECABLE_ETROITE}m"
    decimales = 0 if km >= 10 else 1
    return f"{nombre(km, decimales)}{INSECABLE_ETROITE}km"


def co2_kg(kg: float) -> str:
    """Une masse de CO2 equivalent.

    >>> co2_kg(155.0)
    '155 kg CO2e'
    """
    decimales = 0 if kg >= 10 else 1
    return f"{nombre(kg, decimales)}{INSECABLE_ETROITE}kg{INSECABLE_ETROITE}CO2e"


def date_courte(instant: dt.datetime) -> str:
    """Une date au format court francais, en heure de Paris.

    L'instant doit etre conscient de son fuseau : un instant naif serait ambigu.

    >>> date_courte(dt.datetime(2026, 11, 23, 17, 0, tzinfo=dt.UTC))
    '23 nov.'
    """
    if instant.tzinfo is None:
        raise ValueError("instant naif : le fuseau doit etre explicite")
    local = instant.astimezone(PARIS)
    return f"{local.day}{INSECABLE_ETROITE}{MOIS_ABREGES[local.month - 1]}"


def date_et_heure(instant: dt.datetime) -> str:
    """Date et heure, en heure de Paris.

    >>> date_et_heure(dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.UTC))
    '23 nov. a 17 h 00'
    """
    if instant.tzinfo is None:
        raise ValueError("instant naif : le fuseau doit etre explicite")
    local = instant.astimezone(PARIS)
    heure = f"{local.hour}{INSECABLE_ETROITE}h{INSECABLE_ETROITE}{local.minute:02d}"
    return f"{date_courte(instant)} a {heure}"


def age_relatif(instant: dt.datetime, *, reference: dt.datetime) -> str:
    """L'age d'un prix, dit comme on le dirait a l'oral.

    C'est la formulation utilisee dans les reponses MCP : un modele la restitue mieux
    qu'une date brute, et elle evite de laisser croire a une fraicheur qui n'existe pas.

    >>> ref = dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.UTC)
    >>> age_relatif(ref - dt.timedelta(minutes=7), reference=ref)
    'il y a 7 minutes'
    >>> age_relatif(ref - dt.timedelta(days=3), reference=ref)
    'il y a 3 jours'
    """
    if instant.tzinfo is None or reference.tzinfo is None:
        raise ValueError("instant naif : le fuseau doit etre explicite")
    secondes = (reference - instant).total_seconds()
    if secondes < 0:
        return "a l'instant"
    minutes = int(secondes // 60)
    if minutes < 1:
        return "a l'instant"
    if minutes == 1:
        return "il y a 1 minute"
    if minutes < 60:
        return f"il y a {minutes} minutes"
    heures = minutes // 60
    if heures == 1:
        return "il y a 1 heure"
    if heures < 24:
        return f"il y a {heures} heures"
    jours = heures // 24
    if jours == 1:
        return "hier"
    if jours < 31:
        return f"il y a {jours} jours"
    mois = jours // 30
    return "il y a 1 mois" if mois == 1 else f"il y a {mois} mois"


def pluriel(nombre_d_elements: int, singulier: str, forme_plurielle: str | None = None) -> str:
    """Accorde un nom avec son nombre, en français.

    Le francais met au singulier zero et un : « 0 jour », « 1 jour », « 2 jours ».
    C'est la regle que l'anglais n'a pas, et l'oublier produit « sur 1 jours », ce
    qu'aucun francophone n'ecrit.

    >>> pluriel(0, "jour")
    '0 jour'
    >>> pluriel(1, "jour")
    '1 jour'
    >>> pluriel(2, "jour")
    '2 jours'
    >>> pluriel(3, "station", "stations")
    '3 stations'
    """
    forme = singulier if abs(nombre_d_elements) < 2 else (forme_plurielle or singulier + "s")
    return f"{nombre(nombre_d_elements, 0)}{INSECABLE_ETROITE}{forme}"
