"""Les formats francais sont obligatoires et pieges : ils sont testes caractere a caractere."""

from __future__ import annotations

import datetime as dt

import pytest
from carburant_mcp.formats import (
    INSECABLE_ETROITE,
    age_relatif,
    co2_kg,
    date_courte,
    date_et_heure,
    distance_km,
    euros,
    litres,
    nombre,
    prix_litre,
)

REF = dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.UTC)  # 17h00 a Paris en novembre


@pytest.mark.parametrize(
    ("valeur", "decimales", "attendu"),
    [
        (1.879, 3, "1,879"),
        (0.869, 3, "0,869"),
        (93.95, 2, "93,95"),
        (1234.5, 2, f"1{INSECABLE_ETROITE}234,50"),
        (1234567.0, 0, f"1{INSECABLE_ETROITE}234{INSECABLE_ETROITE}567"),
        (-42.5, 1, "-42,5"),
        (0.0, 2, "0,00"),
    ],
)
def test_nombre(valeur: float, decimales: int, attendu: str) -> None:
    assert nombre(valeur, decimales) == attendu


def test_prix_litre_a_trois_decimales_et_une_espace_insecable() -> None:
    """C'est l'exemple litteral de CLAUDE.md : `1,879 €`."""
    assert prix_litre(1.879) == f"1,879{INSECABLE_ETROITE}€/L"


def test_un_prix_rond_garde_ses_trois_decimales() -> None:
    """En station, 1,90 EUR s'affiche 1,900 : la troisieme decimale fait partie du prix."""
    assert prix_litre(1.9) == f"1,900{INSECABLE_ETROITE}€/L"


def test_euros_et_litres() -> None:
    assert euros(93.95) == f"93,95{INSECABLE_ETROITE}€"
    assert litres(50) == f"50{INSECABLE_ETROITE}L"
    assert litres(42.5) == f"42,5{INSECABLE_ETROITE}L"


@pytest.mark.parametrize(
    ("km", "attendu"),
    [
        (0.35, f"350{INSECABLE_ETROITE}m"),
        (0.999, f"999{INSECABLE_ETROITE}m"),
        (1.0, f"1,0{INSECABLE_ETROITE}km"),
        (2.4, f"2,4{INSECABLE_ETROITE}km"),
        (12.7, f"13{INSECABLE_ETROITE}km"),
    ],
)
def test_distance_km(km: float, attendu: str) -> None:
    assert distance_km(km) == attendu


def test_co2_kg() -> None:
    assert co2_kg(155.0) == f"155{INSECABLE_ETROITE}kg{INSECABLE_ETROITE}CO2e"
    assert co2_kg(3.1) == f"3,1{INSECABLE_ETROITE}kg{INSECABLE_ETROITE}CO2e"


def test_date_courte_est_l_exemple_de_claude_md() -> None:
    """`23 nov.`, avec une espace insecable."""
    assert date_courte(REF) == f"23{INSECABLE_ETROITE}nov."


def test_les_mois_qui_ne_s_abregent_pas() -> None:
    for mois, attendu in ((3, "mars"), (5, "mai"), (6, "juin"), (8, "aout")):
        instant = dt.datetime(2026, mois, 15, 12, 0, tzinfo=dt.UTC)
        assert date_courte(instant).endswith(attendu)


def test_date_courte_bascule_bien_en_heure_de_paris() -> None:
    """Le 31 decembre a 23h30 UTC, il est deja le 1er janvier a Paris."""
    instant = dt.datetime(2025, 12, 31, 23, 30, tzinfo=dt.UTC)
    assert date_courte(instant) == f"1{INSECABLE_ETROITE}janv."


def test_date_et_heure_affiche_l_heure_de_paris() -> None:
    assert (
        date_et_heure(REF)
        == f"23{INSECABLE_ETROITE}nov. a 17{INSECABLE_ETROITE}h{INSECABLE_ETROITE}00"
    )


def test_date_et_heure_en_ete_decale_de_deux_heures() -> None:
    instant = dt.datetime(2026, 7, 15, 12, 30, tzinfo=dt.UTC)
    assert date_et_heure(instant).endswith(f"14{INSECABLE_ETROITE}h{INSECABLE_ETROITE}30")


@pytest.mark.parametrize(
    ("ecart", "attendu"),
    [
        (dt.timedelta(seconds=20), "a l'instant"),
        (dt.timedelta(minutes=1), "il y a 1 minute"),
        (dt.timedelta(minutes=7), "il y a 7 minutes"),
        (dt.timedelta(hours=1), "il y a 1 heure"),
        (dt.timedelta(hours=5), "il y a 5 heures"),
        (dt.timedelta(days=1), "hier"),
        (dt.timedelta(days=3), "il y a 3 jours"),
        (dt.timedelta(days=30), "il y a 30 jours"),
        (dt.timedelta(days=45), "il y a 1 mois"),
        (dt.timedelta(days=90), "il y a 3 mois"),
    ],
)
def test_age_relatif(ecart: dt.timedelta, attendu: str) -> None:
    assert age_relatif(REF - ecart, reference=REF) == attendu


def test_age_relatif_d_une_date_dans_le_futur() -> None:
    """181 dates du flux etaient dans le futur quand on les lisait en UTC : la
    formulation ne doit pas devenir absurde pour autant."""
    assert age_relatif(REF + dt.timedelta(minutes=50), reference=REF) == "a l'instant"


@pytest.mark.parametrize(
    "appel",
    [
        lambda: date_courte(dt.datetime(2026, 11, 23, 17, 0)),  # noqa: DTZ001
        lambda: date_et_heure(dt.datetime(2026, 11, 23, 17, 0)),  # noqa: DTZ001
        lambda: age_relatif(dt.datetime(2026, 11, 23, 17, 0), reference=REF),  # noqa: DTZ001
    ],
)
def test_les_instants_naifs_sont_refuses(appel: object) -> None:
    with pytest.raises(ValueError, match="naif"):
        appel()  # type: ignore[operator]


def test_aucun_format_n_utilise_l_espace_ordinaire_avant_l_unite() -> None:
    """Une espace ordinaire autoriserait un retour a la ligne entre le nombre et son
    unite : c'est precisement ce que l'insecable empeche."""
    for rendu in (prix_litre(1.879), euros(10.0), litres(50), distance_km(2.4), co2_kg(155.0)):
        assert " " not in rendu, rendu
        assert INSECABLE_ETROITE in rendu
