from __future__ import annotations

import pytest
from carburant_etl.carburants import (
    CARBURANTS,
    CODES,
    PAR_CODE,
    CarburantInconnu,
    depuis_nom_flux,
    est_dans_les_bornes,
)


def test_les_six_carburants_publies_et_pas_un_de_plus() -> None:
    """Le flux publie exactement six carburants. GNV et bornes electriques sont
    des *services*, pas des carburants, et n'ont pas de prix publie."""
    assert CODES == ("gazole", "sp95", "e10", "sp98", "e85", "gplc")
    assert len(CARBURANTS) == 6


def test_les_codes_sont_sans_accent_et_en_minuscules() -> None:
    for code in CODES:
        assert code == code.lower()
        assert code.isascii()


@pytest.mark.parametrize(
    ("nom_flux", "code"),
    [
        ("Gazole", "gazole"),
        ("SP95", "sp95"),
        ("E10", "e10"),
        ("SP98", "sp98"),
        ("E85", "e85"),
        ("GPLc", "gplc"),
        # Les archives anciennes ne s'accordent pas avec le flux sur la casse.
        ("gazole", "gazole"),
        ("  GPLC  ", "gplc"),
    ],
)
def test_depuis_nom_flux(nom_flux: str, code: str) -> None:
    assert depuis_nom_flux(nom_flux).code == code


def test_depuis_nom_flux_refuse_un_nom_inconnu_en_listant_les_valeurs_acceptees() -> None:
    with pytest.raises(CarburantInconnu) as erreur:
        depuis_nom_flux("GNV")
    assert "gazole" in str(erreur.value)


@pytest.mark.parametrize(
    ("code", "prix", "accepte"),
    [
        # Valeurs reellement observees le 23/11/2026, qui doivent toutes passer.
        ("gazole", 1.956, True),
        ("gazole", 2.900, True),
        ("e10", 1.790, True),
        ("e10", 2.919, True),
        ("e85", 0.659, True),
        ("e85", 1.313, True),
        ("gplc", 0.825, True),
        ("gplc", 1.420, True),
        # Les 4 vraies erreurs de saisie du jour : des prix de SP95 dans la case E85.
        ("e85", 1.990, False),
        ("e85", 2.249, False),
        # Impossibilites franches.
        ("gazole", 0.019, False),
        ("gazole", 19.9, False),
    ],
)
def test_bornes_absolues(code: str, prix: float, accepte: bool) -> None:
    assert est_dans_les_bornes(code, prix) is accepte


def test_une_borne_commune_a_tous_les_carburants_laisserait_passer_les_erreurs() -> None:
    """La propriete qui compte : un prix peut etre valide pour un carburant et
    aberrant pour un autre.

    1,99 EUR est un prix de gazole parfaitement ordinaire, et c'est en meme temps la
    valeur des trois fausses saisies d'E85 observees le 23/11/2026. Seules des bornes
    **par carburant** distinguent les deux cas.
    """
    assert est_dans_les_bornes("gazole", 1.99) is True
    assert est_dans_les_bornes("e85", 1.99) is False
    assert PAR_CODE["e85"].borne_max < PAR_CODE["gazole"].borne_max


def test_est_dans_les_bornes_refuse_un_code_inconnu() -> None:
    with pytest.raises(CarburantInconnu):
        est_dans_les_bornes("diesel", 1.8)
