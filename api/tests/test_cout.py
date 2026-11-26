"""La fonction de cout reel : tests unitaires et proprietes.

La fonction est pure : elle ne touche ni la base ni le reseau. Elle merite donc
mieux qu'une poignee d'exemples -- des **proprietes**, verifiees sur des milliers de
combinaisons tirees par hypothesis. Une propriete fausse se voit sur un cas qu'on
n'aurait jamais pense a ecrire.
"""

from __future__ import annotations

import pytest
from carburant_api.calcul import cout
from hypothesis import given, settings
from hypothesis import strategies as st

# Bornes physiques plausibles : des prix de carburant, des distances de trajet, des
# volumes de reservoir et des consommations de vehicule.
prix = st.floats(min_value=0.35, max_value=3.50, allow_nan=False, allow_infinity=False)
distances = st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False)
volumes = st.floats(min_value=1.0, max_value=120.0, allow_nan=False, allow_infinity=False)
consommations = st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False)


# ----------------------------------------------------------------- les exemples
def test_un_plein_sans_detour_coute_le_prix_du_plein() -> None:
    """A distance nulle, le cout reel est le prix du plein, sans surprise."""
    d = cout.detail(prix_eur_l=1.800, distance_km=0.0, litres=40.0)
    assert d.cout_detour_eur == 0.0
    assert d.cout_reel_eur == pytest.approx(72.0)


def test_le_detour_est_compte_aller_retour() -> None:
    """10 km a 7 L/100 km, c'est 1,4 L brule : l'aller **et** le retour."""
    d = cout.detail(prix_eur_l=2.000, distance_km=10.0, litres=40.0, consommation_l_100km=7.0)
    assert d.litres_du_detour == pytest.approx(1.4)
    assert d.cout_detour_eur == pytest.approx(2.8)
    assert d.cout_reel_eur == pytest.approx(82.8)


def test_la_station_la_moins_chere_n_est_pas_toujours_la_moins_chere() -> None:
    """Le cas qui justifie tout le projet.

    Une station a 1,75 EUR a 12 km, contre une a 1,80 EUR a 1 km. Au litre, la
    premiere gagne de 5 centimes. En vrai, le detour coute plus que l'economie.
    """
    loin = cout.detail(prix_eur_l=1.750, distance_km=12.0, litres=40.0)
    pres = cout.detail(prix_eur_l=1.800, distance_km=1.0, litres=40.0)
    assert loin.prix_eur_l < pres.prix_eur_l, "la lointaine est bien moins chere au litre"
    assert loin.cout_reel_eur > pres.cout_reel_eur, "mais elle coute plus cher en tout"


def test_une_autonomie_nulle_ne_rend_rien_atteignable() -> None:
    """Le conducteur deja en panne : il n'y a pas de bonne reponse a lui donner."""
    assert cout.atteignable(0.1, autonomie_km=0.0) is False
    assert cout.atteignable(0.1, autonomie_km=-5.0) is False


def test_la_marge_d_autonomie_est_appliquee() -> None:
    """On ne propose pas une station a l'exacte limite du reservoir."""
    # 20 km d'autonomie : on ne va pas au-dela de 16 km.
    assert cout.atteignable(16.0, autonomie_km=20.0) is True
    assert cout.atteignable(16.1, autonomie_km=20.0) is False


def test_l_economie_ne_peut_pas_etre_negative() -> None:
    """Si la plus proche est aussi la meilleure, l economie vaut zero.

    Elle ne devient pas negative : on n'invente pas une perte, on dit qu'il n'y a
    rien a gagner.
    """
    pres = cout.detail(prix_eur_l=1.700, distance_km=1.0)
    loin = cout.detail(prix_eur_l=1.900, distance_km=20.0)
    assert cout.economie(meilleure=loin, reference=pres) == 0.0


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [("prix_eur_l", 0.0), ("prix_eur_l", -1.0), ("distance_km", -1.0), ("litres", 0.0)],
)
def test_une_entree_absurde_est_refusee(champ: str, valeur: float) -> None:
    """Mieux vaut une erreur lisible qu'un cout negatif qui remonte jusqu'a l'ecran."""
    arguments: dict[str, float] = {"prix_eur_l": 1.8, "distance_km": 5.0, "litres": 40.0}
    arguments[champ] = valeur
    with pytest.raises(cout.EntreeInvalide):
        cout.detail(**arguments)


# --------------------------------------------------------------- les proprietes
@given(p=prix, d=distances, litres=volumes, conso=consommations)
@settings(max_examples=400)
def test_le_cout_croit_avec_la_distance(p: float, d: float, litres: float, conso: float) -> None:
    """Aller plus loin ne peut pas couter moins cher, a prix egal."""
    proche = cout.detail(prix_eur_l=p, distance_km=d, litres=litres, consommation_l_100km=conso)
    lointaine = cout.detail(
        prix_eur_l=p, distance_km=d + 1.0, litres=litres, consommation_l_100km=conso
    )
    assert lointaine.cout_reel_eur >= proche.cout_reel_eur


@given(p=prix, d=distances, litres=volumes, conso=consommations)
@settings(max_examples=400)
def test_le_cout_croit_avec_le_prix(p: float, d: float, litres: float, conso: float) -> None:
    """A distance egale, un prix plus eleve ne peut pas donner un cout plus bas."""
    bon_marche = cout.detail(prix_eur_l=p, distance_km=d, litres=litres, consommation_l_100km=conso)
    cher = cout.detail(prix_eur_l=p + 0.1, distance_km=d, litres=litres, consommation_l_100km=conso)
    assert cher.cout_reel_eur >= bon_marche.cout_reel_eur


@given(p=prix, d=distances, litres=volumes, conso=consommations)
@settings(max_examples=400)
def test_le_cout_reel_est_toujours_au_moins_le_prix_du_plein(
    p: float, d: float, litres: float, conso: float
) -> None:
    """Le detour ne peut pas faire economiser du carburant."""
    detail = cout.detail(prix_eur_l=p, distance_km=d, litres=litres, consommation_l_100km=conso)
    assert detail.cout_reel_eur >= detail.cout_plein_eur


@given(p1=prix, d1=distances, p2=prix, d2=distances, litres=volumes, conso=consommations)
@settings(max_examples=400)
def test_l_economie_est_toujours_positive_ou_nulle(
    p1: float, d1: float, p2: float, d2: float, litres: float, conso: float
) -> None:
    """Quelles que soient les deux stations comparees."""
    a = cout.detail(prix_eur_l=p1, distance_km=d1, litres=litres, consommation_l_100km=conso)
    b = cout.detail(prix_eur_l=p2, distance_km=d2, litres=litres, consommation_l_100km=conso)
    assert cout.economie(meilleure=a, reference=b) >= 0.0
    assert cout.economie(meilleure=b, reference=a) >= 0.0


@given(d=distances, autonomie=st.floats(min_value=0.1, max_value=1000.0))
@settings(max_examples=400)
def test_une_station_hors_autonomie_n_est_jamais_atteignable(d: float, autonomie: float) -> None:
    """La propriete de securite : on ne recommande jamais une station hors de portee.

    Tomber en panne en suivant notre conseil serait le pire resultat possible.
    """
    if cout.atteignable(d, autonomie_km=autonomie):
        assert d <= autonomie, "une station atteignable est forcement dans l autonomie brute"
        assert d <= autonomie * cout.MARGE_AUTONOMIE


@given(vol_oiseau=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False))
def test_la_distance_routiere_est_toujours_au_moins_la_distance_a_vol_d_oiseau(
    vol_oiseau: float,
) -> None:
    """La route ne raccourcit pas le trajet."""
    assert cout.distance_routiere(vol_oiseau) >= vol_oiseau
