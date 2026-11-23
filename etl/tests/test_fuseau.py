"""Le fuseau est le piege le plus couteux du projet : il est teste en premier."""

from __future__ import annotations

import datetime as dt

import pytest
from carburant_etl.fuseau import (
    HorodatageIllisible,
    bornes_du_mois_utc,
    en_heure_de_paris,
    jour_de_paris,
    lire_maj,
)


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        # Format du flux data.economie : le suffixe +00:00 est faux, la valeur est
        # de l'heure de Paris. En novembre, Paris est a UTC+1.
        ("2026-11-23T17:00:00+00:00", "2026-11-23T16:00:00+00:00"),
        # Format de la source amont : naif, avec un espace.
        ("2026-11-23 17:00:00", "2026-11-23T16:00:00+00:00"),
        # Format des archives recentes : avec un T, sans fuseau.
        ("2025-01-02T00:37:00", "2025-01-01T23:37:00+00:00"),
        # Archives anciennes : espace et microsecondes.
        ("2007-01-04 18:43:38.841521", "2007-01-04T17:43:38.841521+00:00"),
        # Suffixe Z, egalement faux.
        ("2026-11-23T17:00:00Z", "2026-11-23T16:00:00+00:00"),
    ],
)
def test_lire_maj_interprete_toujours_en_heure_de_paris(valeur: str, attendu: str) -> None:
    assert lire_maj(valeur).isoformat() == attendu


def test_lire_maj_en_ete_decale_de_deux_heures() -> None:
    """En ete, Paris est a UTC+2 : c'est tout l'enjeu du test janvier/juillet."""
    assert lire_maj("2025-07-15T14:30:00+00:00").isoformat() == "2025-07-15T12:30:00+00:00"


def test_lire_maj_ne_perd_pas_une_heure_au_passage_a_l_heure_d_ete() -> None:
    """Le 30 mars 2025, l'heure locale saute de 02h00 a 03h00.

    01h59 est encore en UTC+1, 03h00 est deja en UTC+2 : une minute d'ecart local
    correspond a une minute d'ecart reel, pas a une heure.
    """
    avant = lire_maj("2025-03-30 01:59:00")
    apres = lire_maj("2025-03-30 03:00:00")
    assert avant.isoformat() == "2025-03-30T00:59:00+00:00"
    assert apres.isoformat() == "2025-03-30T01:00:00+00:00"
    assert apres - avant == dt.timedelta(minutes=1)


def test_lire_maj_au_passage_a_l_heure_d_hiver_reste_monotone() -> None:
    """Le 26 octobre 2025, 02h00 locale existe deux fois.

    `zoneinfo` choisit la premiere occurrence par defaut (fold=0), donc UTC+2. On ne
    peut pas faire mieux : la source ne dit pas laquelle des deux. Ce qui compte est
    que la lecture soit deterministe et documentee.
    """
    assert lire_maj("2025-10-26 02:30:00").isoformat() == "2025-10-26T00:30:00+00:00"


def test_lire_maj_refuse_une_chaine_illisible() -> None:
    with pytest.raises(HorodatageIllisible):
        lire_maj("pas une date")


def test_en_heure_de_paris_refuse_un_instant_naif() -> None:
    with pytest.raises(ValueError, match="naif"):
        en_heure_de_paris(dt.datetime(2026, 11, 23, 17, 0))  # noqa: DTZ001


def test_jour_de_paris_rattache_la_premiere_heure_du_mois_au_bon_jour() -> None:
    """Un prix change le 1er janvier a 00h30 a Paris appartient au 1er janvier.

    En UTC il est encore le 31 decembre : c'est exactement le cas qui avait fait
    tomber 3 612 lignes de l'archive 2025 dans la partition DEFAULT.
    """
    instant = lire_maj("2025-01-01 00:30:00")
    assert instant.isoformat() == "2024-12-31T23:30:00+00:00"
    assert jour_de_paris(instant) == dt.date(2025, 1, 1)


def test_bornes_du_mois_sont_alignees_sur_utc() -> None:
    debut, fin = bornes_du_mois_utc(2025, 1)
    assert debut.isoformat() == "2025-01-01T00:00:00+00:00"
    assert fin.isoformat() == "2025-02-01T00:00:00+00:00"


def test_bornes_du_mois_passent_l_annee() -> None:
    debut, fin = bornes_du_mois_utc(2025, 12)
    assert debut.isoformat() == "2025-12-01T00:00:00+00:00"
    assert fin.isoformat() == "2026-01-01T00:00:00+00:00"


def test_un_prix_de_debut_de_mois_local_tombe_dans_le_mois_utc_precedent() -> None:
    """La raison d'etre de `bornes_du_mois_utc` : ce prix doit avoir une partition.

    Sans la partition du mois precedent, il finirait dans la partition DEFAULT, qui
    doit rester vide.
    """
    instant = lire_maj("2025-01-01 00:30:00")
    debut_decembre, fin_decembre = bornes_du_mois_utc(2024, 12)
    assert debut_decembre <= instant < fin_decembre
