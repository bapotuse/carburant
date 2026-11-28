"""Normalisation des noms de carburants côté MCP."""

from __future__ import annotations

import pytest
from carburant_mcp.carburants import (
    CODES,
    LIBELLES,
    CarburantAmbigu,
    CarburantInconnu,
    libelle,
    normaliser,
)


@pytest.mark.parametrize(
    ("terme", "attendu"),
    [
        # Les codes eux-memes
        ("gazole", "gazole"),
        ("sp95", "sp95"),
        ("e10", "e10"),
        ("sp98", "sp98"),
        ("e85", "e85"),
        ("gplc", "gplc"),
        # Ce que les gens disent vraiment
        ("diesel", "gazole"),
        ("Diesel", "gazole"),
        ("DIESEL", "gazole"),
        ("gasoil", "gazole"),
        ("B7", "gazole"),
        ("sans plomb 95", "sp95"),
        ("Sans-Plomb 95", "sp95"),
        ("SANS   PLOMB   95", "sp95"),
        ("sp-95", "sp95"),
        ("95", "sp95"),
        ("super 95", "sp95"),
        ("sp95-e10", "e10"),
        ("E 10", "e10"),
        ("super 98", "sp98"),
        ("98", "sp98"),
        ("superethanol", "e85"),
        ("superéthanol", "e85"),
        ("Super Éthanol", "e85"),
        ("bioéthanol", "e85"),
        ("gpl", "gplc"),
        ("GPL-c", "gplc"),
        ("LPG", "gplc"),
    ],
)
def test_les_synonymes_courants_sont_compris(terme: str, attendu: str) -> None:
    assert normaliser(terme) == attendu


@pytest.mark.parametrize("terme", ["super", "essence", "sans plomb", "sp", "Super", "SANS PLOMB"])
def test_un_terme_ambigu_est_refuse_en_nommant_les_candidats(terme: str) -> None:
    """Deviner afficherait un prix faux sans le dire."""
    with pytest.raises(CarburantAmbigu) as erreur:
        normaliser(terme)
    message = str(erreur.value)
    assert "plusieurs carburants" in message
    assert "sp95" in message, "le refus doit nommer les candidats, pas seulement refuser"


def test_le_plus_precis_gagne_sur_l_ambigu() -> None:
    """« sans plomb » est ambigu, « sans plomb 95 » ne l'est pas."""
    assert normaliser("sans plomb 95") == "sp95"
    with pytest.raises(CarburantAmbigu):
        normaliser("sans plomb")


@pytest.mark.parametrize("terme", ["kerosene", "charbon", "sp97", "", "   ", "e86"])
def test_un_terme_inconnu_liste_les_valeurs_acceptees(terme: str) -> None:
    with pytest.raises(CarburantInconnu) as erreur:
        normaliser(terme)
    message = str(erreur.value)
    for code in CODES:
        assert code in message, f"le code {code} doit figurer dans l'erreur"


def test_tout_synonyme_rend_un_code_connu() -> None:
    """Propriete : aucune entree de la table ne peut pointer vers un code fantome."""
    from carburant_mcp.carburants import _AMBIGUS, _SYNONYMES

    for terme, code in _SYNONYMES.items():
        assert code in CODES, f"le synonyme « {terme} » pointe vers « {code} », inconnu"
    for terme, candidats in _AMBIGUS.items():
        assert len(candidats) >= 2, f"« {terme} » n'a qu'un candidat : ce n'est pas ambigu"
        for code in candidats:
            assert code in CODES, f"« {terme} » propose « {code} », inconnu"


def test_chaque_code_a_un_libelle_francais() -> None:
    """« sp95 » est un code, pas du francais : une reponse ne doit jamais l'afficher nu."""
    for code in CODES:
        assert code in LIBELLES
        assert libelle(code) != code or code == "gazole", (
            f"« {code} » doit avoir un libelle lisible different du code"
        )


def test_les_codes_sont_les_memes_que_ceux_de_l_etl() -> None:
    """La seule chose qui doit coincider entre les deux paquets.

    `carburant_mcp` est publie seul sur PyPI et ne depend pas de l'ETL : les tables de
    synonymes sont donc distinctes a dessein. Mais les six **codes** sont le contrat
    de l'API, et une divergence la ferait repondre 422 sur un carburant valide.
    """
    from carburant_etl.carburants import CODES as CODES_ETL

    assert set(CODES) == set(CODES_ETL)
