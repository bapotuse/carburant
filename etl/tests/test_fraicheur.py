from __future__ import annotations

import datetime as dt

import pytest
from carburant_etl.transformation.fraicheur import (
    Fraicheur,
    classer,
    utilisable_en_classement,
    utilisable_en_recherche,
)

MAINTENANT = dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("age", "attendu"),
    [
        (dt.timedelta(minutes=10), Fraicheur.FRAIS),
        (dt.timedelta(hours=47, minutes=59), Fraicheur.FRAIS),
        (dt.timedelta(hours=48), Fraicheur.FRAIS),
        (dt.timedelta(hours=48, seconds=1), Fraicheur.RECENT),
        (dt.timedelta(days=7), Fraicheur.RECENT),
        (dt.timedelta(days=7, seconds=1), Fraicheur.ANCIEN),
        (dt.timedelta(days=30), Fraicheur.ANCIEN),
        (dt.timedelta(days=30, seconds=1), Fraicheur.PERIME),
        (dt.timedelta(days=237), Fraicheur.PERIME),
    ],
)
def test_classement_aux_bornes(age: dt.timedelta, attendu: Fraicheur) -> None:
    assert classer(MAINTENANT - age, reference=MAINTENANT) is attendu


def test_une_maj_dans_le_futur_est_traitee_comme_fraiche() -> None:
    """181 dates du flux etaient dans le futur quand on les lisait en UTC. Ce n'est
    pas a l'affichage de s'en plaindre, mais au controle qualite max(maj) <= now()."""
    futur = MAINTENANT + dt.timedelta(minutes=50)
    assert classer(futur, reference=MAINTENANT) is Fraicheur.FRAIS


def test_classer_refuse_une_date_naive() -> None:
    with pytest.raises(ValueError, match="naive"):
        classer(dt.datetime(2026, 11, 23, 16, 0), reference=MAINTENANT)  # noqa: DTZ001


def test_un_prix_ancien_reste_cherchable_mais_sort_des_classements() -> None:
    """C'est le coeur de la decision 1.1 : on ne prive pas l'utilisateur d'une station
    qui existe, mais on ne laisse pas un prix de 3 semaines fausser une moyenne."""
    assert utilisable_en_recherche(Fraicheur.ANCIEN) is True
    assert utilisable_en_classement(Fraicheur.ANCIEN) is False


def test_un_prix_perime_sort_des_recherches() -> None:
    assert utilisable_en_recherche(Fraicheur.PERIME) is False
    assert utilisable_en_classement(Fraicheur.PERIME) is False


@pytest.mark.parametrize("fraicheur", [Fraicheur.FRAIS, Fraicheur.RECENT])
def test_les_prix_frais_et_recents_sont_utilisables_partout(fraicheur: Fraicheur) -> None:
    assert utilisable_en_recherche(fraicheur)
    assert utilisable_en_classement(fraicheur)
