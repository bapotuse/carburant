"""Chargement vers marts, contre une vraie base PostGIS.

Le test central est `test_deux_executions_ne_creent_aucun_doublon` : c'est le critere
de sortie du Jalon 1, et il ne peut se verifier que contre une vraie base.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from carburant_etl.chargement import marts
from carburant_etl.chargement.migrations import appliquer
from carburant_etl.chargement.staging import charger as charger_staging
from carburant_etl.chargement.staging import ouvrir
from carburant_etl.modeles import Aplatissement, LignePrix, LigneStation, Rejets
from carburant_etl.sources.flux_v2 import Collecte

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")


@pytest.fixture
def base() -> Iterator[str]:
    assert URL
    nom = f"carburant_marts_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(URL, autocommit=True) as administration:
        administration.execute(f'CREATE DATABASE "{nom}"')
    url_test = URL.rsplit("/", 1)[0] + f"/{nom}"
    try:
        appliquer(url_test)
        yield url_test
    finally:
        with psycopg.connect(URL, autocommit=True) as administration:
            administration.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nom,),
            )
            administration.execute(f'DROP DATABASE IF EXISTS "{nom}"')


def collecte(instant: dt.datetime, sha: str = "a" * 64) -> Collecte:
    return Collecte(
        source="flux-v2",
        url="https://exemple/exports/json",
        debut=instant,
        fin=instant + dt.timedelta(seconds=3),
        octets=1234,
        sha256=sha,
        chemin=Path("/brut/flux.json.gz"),
        inchange=False,
    )


def station(identifiant: int = 56580001, **surcharges: object) -> LigneStation:
    defauts: dict[str, object] = {
        "station_id": identifiant,
        "longitude": -2.69,
        "latitude": 48.061,
        "cp": "56580",
        "adresse": "16 rue chateaubriand",
        "ville": "Brehan",
        "pop": "R",
        "departement": "Morbihan",
        "code_departement": "56",
        "region": "Bretagne",
        "code_region": "53",
        "horaires": {"automate_24_24": True, "jours": []},
        "services": ["Automate CB 24/24"],
    }
    defauts.update(surcharges)
    return LigneStation(**defauts)  # type: ignore[arg-type]


def prix(
    maj: str,
    valeur: float = 2.109,
    carburant: str = "gazole",
    identifiant: int = 56580001,
) -> LignePrix:
    return LignePrix(
        station_id=identifiant,
        carburant=carburant,
        prix=valeur,
        maj=maj,
        rupture_type=None,
        rupture_debut=None,
    )


def nombre(valeur: object) -> float:
    """Convertit une valeur sortie de la base en nombre.

    `fetchone` rend `tuple[object, ...]` : on verifie le type plutot que de le forcer.
    """
    from decimal import Decimal

    assert isinstance(valeur, (int, float, Decimal)), f"nombre attendu : {valeur!r}"
    return float(valeur)


def charger_tout(
    connexion: psycopg.Connection[tuple[object, ...]],
    instant: dt.datetime,
    stations: list[LigneStation],
    lignes: list[LignePrix],
    sha: str = "a" * 64,
) -> marts.ResultatMarts:
    """Charge staging puis marts, comme le fait le pipeline."""
    aplati = Aplatissement(
        stations=stations, prix=lignes, rejets=Rejets(), lignes_lues=len(stations)
    )
    collecte_id = charger_staging(connexion, collecte(instant, sha), aplati)
    return marts.charger(connexion, collecte_id)


T0 = dt.datetime(2026, 11, 24, 12, 0, tzinfo=dt.UTC)


# ---------------------------------------------------------------- idempotence


@sans_base
def test_deux_executions_ne_creent_aucun_doublon(base: str) -> None:
    """Le critere de sortie du Jalon 1.

    Le grain etant « un changement de prix », deux collectes successives voient les
    memes `(station, carburant, maj)` : la seconde ne doit rien inserer et se
    contenter d'avancer `derniere_observation`.
    """
    # Deux carburants, pas deux prix du meme carburant : le staging a pour grain
    # (collecte, station, carburant), et le flux ne publie qu'un prix courant par
    # carburant et par station.
    lignes = [
        prix("2026-11-23T16:00:00+00:00"),
        prix("2026-11-20T09:00:00+00:00", 1.949, carburant="e10"),
    ]

    with ouvrir(base) as connexion:
        premier = charger_tout(connexion, T0, [station()], lignes)
        second = charger_tout(
            connexion, T0 + dt.timedelta(minutes=15), [station()], lignes, sha="b" * 64
        )

        curseur = connexion.execute("SELECT count(*) FROM marts.fact_prix")
        total = curseur.fetchone()
        curseur = connexion.execute(
            "SELECT derniere_observation FROM marts.fact_prix "
            "WHERE maj = '2026-11-23T16:00:00+00:00'"
        )
        observation = curseur.fetchone()

    assert premier.prix_inseres == 2
    assert premier.prix_revus == 0
    assert second.prix_inseres == 0, "la seconde execution ne doit rien inserer"
    assert second.prix_revus == 2
    assert total == (2,)
    # La seule colonne touchee est la derniere observation.
    assert observation is not None
    assert observation[0] == T0 + dt.timedelta(minutes=15)


@sans_base
def test_un_nouveau_changement_de_prix_ajoute_une_ligne(base: str) -> None:
    with ouvrir(base) as connexion:
        charger_tout(connexion, T0, [station()], [prix("2026-11-23T16:00:00+00:00")])
        # La station a change son prix de gazole : nouvelle `maj`, nouveau prix.
        second = charger_tout(
            connexion,
            T0 + dt.timedelta(minutes=15),
            [station()],
            [prix("2026-11-24T11:00:00+00:00", 2.129)],
            sha="b" * 64,
        )
        curseur = connexion.execute("SELECT prix FROM marts.fact_prix ORDER BY maj")
        prix_en_base = [ligne[0] for ligne in curseur.fetchall()]

    assert second.prix_inseres == 1
    assert second.prix_revus == 0
    # L'ancien prix reste : c'est un historique de changements, pas un etat courant.
    assert [nombre(p) for p in prix_en_base] == [2.109, 2.129]


# ---------------------------------------------------------------- partitions


@sans_base
def test_les_partitions_couvrent_les_dates_anciennes(base: str) -> None:
    """`maj` est une date de CHANGEMENT : elle peut remonter a plus d'un an.

    483 jours constates pour le SP95. S'en tenir au mois courant et au suivant, comme
    le proposait la specification, remplirait la partition DEFAULT.
    """
    with ouvrir(base) as connexion:
        resultat = charger_tout(
            connexion,
            T0,
            [station()],
            [
                prix("2025-07-15T10:00:00+00:00", carburant="sp95"),
                prix("2026-11-23T16:00:00+00:00"),
            ],
        )
        assert marts.partition_defaut_vide(connexion) == 0

    assert "fact_prix_202507" in resultat.partitions_creees
    assert "fact_prix_202611" in resultat.partitions_creees
    # Le mois suivant est toujours cree d'avance.
    assert "fact_prix_202612" in resultat.partitions_creees


@sans_base
def test_la_premiere_heure_du_mois_a_paris_ne_tombe_pas_dans_le_defaut(
    base: str,
) -> None:
    """Le piege mesure : 00h30 le 1er janvier a Paris, c'est le 31 decembre en UTC.

    3 612 lignes de l'archive 2025 etaient tombees dans la partition DEFAULT a cause
    de bornes ecrites sans fuseau.
    """
    with ouvrir(base) as connexion:
        charger_tout(
            connexion,
            T0,
            [station()],
            # 2025-01-01 00h30 a Paris = 2024-12-31 23h30 UTC.
            [prix("2024-12-31T23:30:00+00:00")],
        )
        assert marts.partition_defaut_vide(connexion) == 0
        curseur = connexion.execute("SELECT count(*) FROM marts.fact_prix_202412")
        ligne = curseur.fetchone()
    assert ligne == (1,), "la ligne doit etre dans la partition de decembre UTC"


@sans_base
def test_les_partitions_ne_sont_creees_qu_une_fois(base: str) -> None:
    with ouvrir(base) as connexion:
        premier = charger_tout(connexion, T0, [station()], [prix("2026-11-23T16:00:00+00:00")])
        second = charger_tout(
            connexion,
            T0 + dt.timedelta(minutes=15),
            [station()],
            [prix("2026-11-23T16:00:00+00:00")],
            sha="b" * 64,
        )
    assert premier.partitions_creees
    assert second.partitions_creees == []


# ---------------------------------------------------------------- dim_station


@sans_base
def test_la_station_est_mise_a_jour_en_place(base: str) -> None:
    """SCD de type 1 : la premiere vue ne bouge pas, la derniere avance."""
    with ouvrir(base) as connexion:
        charger_tout(connexion, T0, [station()], [])
        charger_tout(
            connexion,
            T0 + dt.timedelta(hours=1),
            [station(ville="Brehan-sur-Mer")],
            [],
            sha="b" * 64,
        )
        curseur = connexion.execute(
            "SELECT ville, premiere_vue, derniere_vue, autoroute FROM marts.dim_station"
        )
        lignes = curseur.fetchall()

    assert len(lignes) == 1, "une seule ligne par station"
    assert lignes[0][0] == "Brehan-sur-Mer"
    assert lignes[0][1] == T0
    assert lignes[0][2] == T0 + dt.timedelta(hours=1)
    assert lignes[0][3] is False


@sans_base
def test_l_autoroute_est_derivee_de_pop(base: str) -> None:
    with ouvrir(base) as connexion:
        charger_tout(connexion, T0, [station(pop="A")], [])
        curseur = connexion.execute("SELECT autoroute FROM marts.dim_station")
        ligne = curseur.fetchone()
    assert ligne == (True,)


@sans_base
def test_la_geometrie_permet_une_recherche_de_proximite(base: str) -> None:
    """Le point doit etre une vraie geographie, pas deux nombres."""
    with ouvrir(base) as connexion:
        charger_tout(connexion, T0, [station()], [])
        curseur = connexion.execute(
            """
            SELECT round(ST_Distance(
                geom, ST_SetSRID(ST_MakePoint(-2.70, 48.07), 4326)::geography
            )::numeric)
            FROM marts.dim_station
            """
        )
        ligne = curseur.fetchone()
    assert ligne is not None
    # Environ 1,2 km entre les deux points : on verifie l'ordre de grandeur.
    assert 800 < nombre(ligne[0]) < 1600, ligne[0]


@sans_base
def test_une_station_absente_est_desactivee_puis_reactivee(base: str) -> None:
    """Jamais supprimee : son historique de prix doit rester consultable."""
    with ouvrir(base) as connexion:
        charger_tout(connexion, T0, [station()], [])

        for i in range(marts.COLLECTES_MANQUEES_AVANT_INACTIVE):
            charger_tout(
                connexion,
                T0 + dt.timedelta(minutes=15 * (i + 1)),
                [station(identifiant=99999999)],
                [],
                sha=f"{i}" * 64,
            )

        curseur = connexion.execute(
            "SELECT active, collectes_manquees FROM marts.dim_station WHERE id = 56580001"
        )
        apres_absences = curseur.fetchone()

        charger_tout(connexion, T0 + dt.timedelta(hours=5), [station()], [], sha="f" * 64)
        curseur = connexion.execute(
            "SELECT active, collectes_manquees FROM marts.dim_station WHERE id = 56580001"
        )
        apres_retour = curseur.fetchone()

    assert apres_absences == (False, marts.COLLECTES_MANQUEES_AVANT_INACTIVE)
    assert apres_retour == (True, 0), "une station qui reapparait redevient active"


# ---------------------------------------------------------------- ruptures


@sans_base
def test_une_rupture_est_chargee_puis_levee(base: str) -> None:
    rupture = LignePrix(
        station_id=56580001,
        carburant="gplc",
        prix=None,
        maj=None,
        rupture_type="definitive",
        rupture_debut="2017-10-06T14:05:31+00:00",
    )
    with ouvrir(base) as connexion:
        charger_tout(connexion, T0, [station()], [rupture])
        curseur = connexion.execute("SELECT carburant, type FROM marts.rupture")
        pendant = curseur.fetchall()

        # Collecte suivante : la rupture a disparu du flux.
        charger_tout(connexion, T0 + dt.timedelta(minutes=15), [station()], [], sha="b" * 64)
        curseur = connexion.execute("SELECT count(*) FROM marts.rupture")
        apres = curseur.fetchone()

    assert pendant == [("gplc", "definitive")]
    assert apres == (0,), "une rupture levee doit disparaitre de l'etat courant"


# ---------------------------------------------------------------- coherence


@sans_base
def test_dim_carburant_correspond_a_la_table_du_code(base: str) -> None:
    """La migration garnit `dim_carburant` ; `carburant_etl.carburants` fait foi.

    Si les deux divergent, une pastille, une borne ou un libelle sera faux quelque
    part sans que rien ne proteste.
    """
    from carburant_etl.carburants import CARBURANTS

    with psycopg.connect(base) as connexion:
        curseur = connexion.execute(
            "SELECT code, libelle, nom_flux, token_couleur, forme, borne_min, borne_max "
            "FROM marts.dim_carburant ORDER BY ordre"
        )
        en_base = curseur.fetchall()

    attendu = [
        (
            c.code,
            c.libelle,
            c.nom_flux,
            c.token_couleur,
            c.forme,
            c.borne_min,
            c.borne_max,
        )
        for c in CARBURANTS
    ]
    assert [(a, b, c, d, e, nombre(f), nombre(g)) for a, b, c, d, e, f, g in en_base] == attendu
