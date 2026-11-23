"""Lecture des horodatages des sources, et le piege de fuseau qui va avec.

Les dates `maj` du flux des prix sont de l'**heure locale Europe/Paris**. data.economie
les sert pourtant avec un suffixe `+00:00`, qui est faux. Trois constats et une preuve,
detailles dans docs/reconnaissance.md section 1.4 :

- 181 dates du flux sont dans le futur si on les lit en UTC ;
- le jeu declare avoir ete moissonne a 15h53 UTC tout en contenant des `maj` a 16h50
  « UTC », soit 57 minutes apres la moisson ;
- la source amont donne les memes dates sans aucun fuseau ;
- sur les 5,3 millions d'horodatages de 2025, le profil horaire de janvier (UTC+1) et
  celui de juillet (UTC+2) se superposent : correlation 0,9987 a decalage nul, contre
  0,18 a une heure de decalage. En UTC, juillet serait decale. Il ne l'est pas.

Lire ces dates en UTC decalerait donc tous les prix d'une heure en hiver et de deux en
ete, en silence. Toutes les entrees d'horodatage du projet passent par ce module.

Les formats rencontres, dans un meme fichier et selon l'annee :
`2026-11-23T17:00:00`, `2026-11-23 17:00:00`, `2007-01-04 18:43:38.841521`,
et la version etiquetee par data.economie `2026-11-23T17:00:00+00:00`.
"""

from __future__ import annotations

import datetime as dt
from typing import Final
from zoneinfo import ZoneInfo

PARIS: Final = ZoneInfo("Europe/Paris")
UTC: Final = dt.UTC


class HorodatageIllisible(ValueError):
    """Leve quand une chaine ne ressemble a aucun format connu de la source."""

    def __init__(self, valeur: str) -> None:
        self.valeur = valeur
        super().__init__(f"horodatage illisible : {valeur!r}")


def _sans_suffixe_de_fuseau(valeur: str) -> str:
    """Retire le suffixe de fuseau, qui est faux quand il vient de data.economie.

    On ne retire que ce qui suit la partie date-heure : le `+00:00` ou le `Z` ajoute
    par Opendatasoft. La valeur elle-meme est de l'heure locale de Paris.
    """
    texte = valeur.strip()
    if texte.endswith("Z"):
        return texte[:-1]
    # Un fuseau explicite apparait apres les 19 premiers caracteres (AAAA-MM-JJ?HH:MM:SS)
    # ou apres les microsecondes. On cherche le dernier + ou - qui suit l'heure.
    for i in range(len(texte) - 1, 9, -1):
        if texte[i] in "+-":
            return texte[:i]
    return texte


def lire_maj(valeur: str) -> dt.datetime:
    """Lit une date `maj` de la source et renvoie un datetime conscient du fuseau.

    La valeur est interpretee en Europe/Paris, quel que soit le suffixe annonce.
    Le resultat est converti en UTC : c'est ce qu'on stocke dans un `timestamptz`.

    >>> lire_maj("2026-11-23T17:00:00+00:00").isoformat()
    '2026-11-23T16:00:00+00:00'
    >>> lire_maj("2007-01-04 18:43:38.841521").isoformat()
    '2007-01-04T17:43:38.841521+00:00'
    """
    texte = _sans_suffixe_de_fuseau(valeur).replace("T", " ", 1)
    for format_ in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            naif = dt.datetime.strptime(texte, format_)  # noqa: DTZ007 - localise juste apres
        except ValueError:
            continue
        return naif.replace(tzinfo=PARIS).astimezone(UTC)
    raise HorodatageIllisible(valeur)


def maintenant() -> dt.datetime:
    """L'instant present, en UTC. Un seul point d'entree, pour pouvoir le figer en test."""
    return dt.datetime.now(tz=UTC)


def en_heure_de_paris(instant: dt.datetime) -> dt.datetime:
    """Convertit un instant en heure de Paris, pour l'affichage et les agregats par jour."""
    if instant.tzinfo is None:
        raise ValueError("instant naif : le fuseau doit etre explicite")
    return instant.astimezone(PARIS)


def jour_de_paris(instant: dt.datetime) -> dt.date:
    """Le jour calendaire de Paris auquel appartient un instant.

    C'est la bonne date pour `snapshot_prix_jour` : un prix change le 1er janvier a
    00h30 a Paris appartient au 1er janvier, meme s'il est encore le 31 decembre en UTC.
    """
    return en_heure_de_paris(instant).date()


def bornes_du_mois_utc(annee: int, mois: int) -> tuple[dt.datetime, dt.datetime]:
    """Bornes UTC d'une partition mensuelle de `fact_prix`.

    Les bornes sont alignees sur le mois **UTC**, parce que PostgreSQL interprete les
    bornes d'une partition `timestamptz` en UTC. Ecrire `FROM ('2025-01-01')` sans
    fuseau fait tomber les prix du 1er janvier entre 00h00 et 00h58 heure de Paris dans
    la partition precedente -- ou, si elle n'existe pas, dans la partition DEFAULT.
    Mesure : 3 612 lignes de l'archive 2025 (docs/reconnaissance.md section 2.5).
    """
    debut = dt.datetime(annee, mois, 1, tzinfo=UTC)
    fin = dt.datetime(annee + (mois == 12), mois % 12 + 1, 1, tzinfo=UTC)
    return debut, fin
