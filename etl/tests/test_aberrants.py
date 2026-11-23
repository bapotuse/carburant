from __future__ import annotations

import pytest
from carburant_etl.transformation.aberrants import (
    FACTEUR_MAD,
    PLANCHER_MAD,
    ecart_en_mad,
    est_suspect,
    mediane_et_mad,
)


def test_mediane_et_mad() -> None:
    mediane, mad = mediane_et_mad([1.90, 1.95, 2.00, 2.05, 2.10])
    assert mediane == 2.00
    assert round(mad, 3) == 0.050


def test_le_plancher_de_mad_evite_de_signaler_un_prix_normal() -> None:
    """Le cas reel qui cassait la regle de la spec : en Haute-Corse, la MAD du gazole
    descend a 0,0005 EUR parce que beaucoup de stations affichent le meme prix. Un prix
    de 2,29 EUR face a une mediane de 2,23 se retrouvait alors a 120 MAD.
    """
    prix, mediane, mad = 2.29, 2.23, 0.0005
    # Sans plancher, la regle brute signalerait ce prix.
    assert abs(prix - mediane) / mad > 100
    # Avec le plancher, non.
    assert est_suspect(prix, mediane, mad, nombre_de_stations=59) is False


def test_une_vraie_station_hors_norme_est_bien_signalee() -> None:
    """L'Ile-d'Yeu, SP95 a 2,613 EUR face a 1,99 EUR en Vendee."""
    assert est_suspect(2.613, 1.99, 0.032, nombre_de_stations=120) is True


def test_une_erreur_de_saisie_e85_est_signalee() -> None:
    """Cauterets, E85 a 2,249 EUR face a 0,935 dans les Hautes-Pyrenees.
    Les bornes absolues l'auraient deja rejetee ; la regle relative la confirme."""
    assert est_suspect(2.249, 0.935, 0.023, nombre_de_stations=30) is True


def test_un_departement_trop_petit_ne_juge_personne() -> None:
    assert est_suspect(2.90, 2.10, 0.01, nombre_de_stations=4) is False


def test_la_limite_exacte_du_signalement() -> None:
    mediane = 2.00
    # Avec une MAD nulle, l'echelle est le plancher : la limite est a 5 x 0,05 = 0,25.
    limite = FACTEUR_MAD * PLANCHER_MAD
    assert est_suspect(mediane + limite, mediane, 0.0, nombre_de_stations=50) is False
    assert est_suspect(mediane + limite + 0.001, mediane, 0.0, nombre_de_stations=50) is True


def test_l_ecart_en_mad_est_stocke_pour_rendre_le_signalement_verifiable() -> None:
    # On compare des flottants issus d'une division : l'egalite exacte n'a pas de sens.
    # MAD sous le plancher : c'est le plancher qui sert d'echelle.
    assert ecart_en_mad(2.25, 2.00, 0.0005) == pytest.approx(5.0)
    # MAD au dessus du plancher : c'est la MAD reelle.
    assert ecart_en_mad(2.30, 2.00, 0.10) == pytest.approx(3.0)
