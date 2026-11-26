"""Lecture et chargement des archives annuelles.

Le schema de ces archives change selon l'annee, et les donnees y sont sales : prix
en millemes jusqu'en 2021 puis en euros, deux formats de date **dans un meme
fichier**, coordonnees x 100 000 parfois non entieres et parfois aberrantes, et
environ 4 658 elements `<prix>` vides par archive. Chaque test ci-dessous reproduit
une de ces saletes.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from carburant_etl.chargement import backfill
from carburant_etl.chargement.migrations import appliquer
from carburant_etl.chargement.staging import ouvrir
from carburant_etl.sources import archives

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")


# ------------------------------------------------------------- les conversions
@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        (999, 0.999),  # millemes, archive 2007
        (1525, 1.525),  # millemes, archive 2021
        (1.809, 1.809),  # euros, archive 2022
        (0.869, 0.869),  # euros, E85
        (20.0, 20.0),  # pile au seuil : pas converti
        (20.001, 0.020001),  # juste au-dessus : converti
    ],
)
def test_la_conversion_des_prix_ne_depend_pas_de_l_annee(brut: float, attendu: float) -> None:
    """`si valeur > 20 alors valeur / 1000` : aucun carburant n'a valu 20 EUR le litre.

    La regle marche sur les deux eres sans savoir en quelle annee on est, ce qui la
    rend robuste a une bascule d'unite qu'on n'aurait pas vue venir.
    """
    assert archives.convertir_prix(brut) == pytest.approx(attendu)


def test_les_coordonnees_ne_sont_pas_toujours_entieres() -> None:
    """3 539 valeurs decimales dans la seule archive 2025."""
    assert archives.convertir_coordonnee("4620114") == pytest.approx(46.20114)
    assert archives.convertir_coordonnee("6260655.98007") == pytest.approx(62.6065598007)


@pytest.mark.parametrize(
    ("longitude", "latitude", "dedans"),
    [
        (5.19791, 46.20114, True),  # Bourg-en-Bresse
        (9.15, 41.59, True),  # Corse-du-Sud : dans l'emprise
        (55.49, -20.95, False),  # La Reunion : vraie station, hors emprise
        (5.39, 62.6, False),  # au nord de la Norvege : aberration pure
    ],
)
def test_l_emprise_ecarte_les_drom_et_les_aberrations(
    longitude: float, latitude: float, dedans: bool
) -> None:
    assert archives.dans_l_emprise(longitude, latitude) is dedans


@pytest.mark.parametrize(
    ("cp", "attendu"),
    [
        ("01000", "01"),
        ("13008", "13"),
        ("20000", None),  # Corse : 2A ou 2B ? on ne devine pas
        ("97400", None),  # DROM : de toute facon hors emprise
        (None, None),
        ("", None),
    ],
)
def test_le_departement_se_deduit_du_code_postal(cp: str | None, attendu: str | None) -> None:
    """Les archives ne donnent pas le departement, contrairement au flux."""
    assert backfill.departement_depuis_cp(cp) == attendu


def test_les_partitions_couvrent_decembre_precedent() -> None:
    """Un prix du 1er janvier a 00 h 30 a Paris est un 31 decembre en UTC.

    Sans la partition de decembre precedent, il tomberait dans la partition DEFAULT,
    qui doit rester vide. Mesure : 3 612 lignes pour l'archive 2025.
    """
    mois = backfill.mois_de_l_annee(2025)
    assert (2024, 12) in mois
    assert len(mois) == 13


# --------------------------------------------------------------- le parseur
def archive_minimale(chemin: Path, contenu: str) -> Path:
    """Fabrique un zip d'archive, encode en ISO-8859-1 comme les vraies."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(chemin, "w") as zf:
        zf.writestr("PrixCarburants_annuel.xml", contenu.encode("latin-1"))
    return chemin


XML_SALE = """<?xml version="1.0" encoding="ISO-8859-1" standalone="yes"?><pdv_liste>
<pdv id="1000001" latitude="4620114" longitude="519791" cp="01000" pop="R">
  <adresse>ROUTE NATIONALE</adresse>
  <ville>SAINT-DENIS-L\xe8S-BOURG</ville>
  <prix nom="Gazole" id="1" maj="2007-01-04 18:43:38.841521" valeur="999"/>
  <prix nom="SP95" id="2" maj="2007-01-05T08:00:00" valeur="1170"/>
  <prix/>
  <prix nom="Super" id="9" maj="2007-01-06T08:00:00" valeur="1200"/>
  <prix nom="Gazole" id="1" maj="2007-01-07T08:00:00" valeur="99999"/>
  <prix nom="Gazole" id="1" maj="pas une date" valeur="1000"/>
</pdv>
<pdv id="9740001" latitude="-2094971" longitude="5529526" cp="97400" pop="R">
  <adresse>LA REUNION</adresse><ville>SAINT-DENIS</ville>
  <prix nom="Gazole" id="1" maj="2007-01-04T08:00:00" valeur="1100"/>
</pdv>
<pdv id="1200004" cp="12000" pop="R"><adresse>SANS COORDONNEES</adresse><ville>RODEZ</ville></pdv>
</pdv_liste>
"""


def test_le_parseur_encaisse_une_archive_sale(tmp_path: Path) -> None:
    chemin = archive_minimale(tmp_path / "archive-2007.zip", XML_SALE)
    iterateur, rejets = archives.lire(chemin)
    lues = list(iterateur)

    assert len(lues) == 1, "seule la station metropolitaine doit sortir"
    station, prix = lues[0]
    assert station.station_id == 1000001
    assert station.ville == "SAINT-DENIS-LèS-BOURG", "l archive est en ISO-8859-1"
    assert station.longitude == pytest.approx(5.19791)

    assert [(p.carburant, p.prix) for p in prix] == [("gazole", 0.999), ("sp95", 1.170)]

    assert rejets.stations_hors_emprise == 1, "La Reunion"
    assert rejets.stations_sans_coordonnees == 1
    assert rejets.prix_malformes == 1, "le <prix/> vide"
    assert rejets.carburants_inconnus == 1, "« Super » n est pas un carburant du flux"
    assert rejets.prix_hors_bornes == 1, "99,999 EUR le litre"
    assert rejets.maj_illisibles == 1
    assert rejets.total == 6


def test_les_deux_formats_de_date_coexistent(tmp_path: Path) -> None:
    """2025 contient 5 297 800 dates au format `T` et 96 au format espace."""
    chemin = archive_minimale(tmp_path / "archive-2007.zip", XML_SALE)
    iterateur, _ = archives.lire(chemin)
    _, prix = next(iter(iterateur))
    espace, avec_t = prix[0], prix[1]
    # Les deux sont lues, et les deux sont localisees en heure de Paris : janvier
    # est en UTC+1, donc 18 h 43 a Paris fait 17 h 43 en UTC.
    assert espace.maj == dt.datetime(2007, 1, 4, 17, 43, 38, 841521, tzinfo=dt.UTC)
    assert avec_t.maj == dt.datetime(2007, 1, 5, 7, 0, tzinfo=dt.UTC)


def test_une_archive_vide_leve(tmp_path: Path) -> None:
    chemin = tmp_path / "vide.zip"
    with zipfile.ZipFile(chemin, "w"):
        pass
    iterateur, _ = archives.lire(chemin)
    with pytest.raises(ValueError, match="archive vide"):
        list(iterateur)


# ------------------------------------------------------------- le chargement
@pytest.fixture
def base() -> Iterator[str]:
    assert URL
    nom = f"carburant_archive_{uuid.uuid4().hex[:12]}"
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


@pytest.mark.integration
@sans_base
def test_amorcer_deux_fois_n_ajoute_rien(base: str, tmp_path: Path) -> None:
    """Une archive a moitie chargee, une coupure, un essai : rejouer doit etre sans effet."""
    archive_minimale(tmp_path / "archive-2007.zip", XML_SALE)
    connexion = ouvrir(base)
    try:
        premier = backfill.amorcer(
            connexion, 2007, repertoire=tmp_path, user_agent="tests", taille_lot=10
        )
        second = backfill.amorcer(
            connexion, 2007, repertoire=tmp_path, user_agent="tests", taille_lot=10
        )
        with connexion.cursor() as curseur:
            curseur.execute("SELECT count(*) FROM marts.fact_prix")
            total = curseur.fetchone()
            curseur.execute("SELECT count(*) FROM marts.fact_prix_defaut")
            defaut = curseur.fetchone()
    finally:
        connexion.close()
    assert premier.prix_inseres == 2
    assert second.prix_inseres == 0
    assert second.prix_deja_connus == 2
    assert total is not None and total[0] == 2
    assert defaut is not None and defaut[0] == 0, "la partition DEFAULT doit rester vide"


@pytest.mark.integration
@sans_base
def test_une_station_connue_du_flux_n_est_pas_ecrasee(base: str, tmp_path: Path) -> None:
    """L'archive 2007 ne doit pas remplacer l'adresse a jour d'une station vivante.

    Elle avance seulement sa premiere vue vers le passe : c'est tout ce que
    l'histoire ancienne apprend sur une station encore en activite.
    """
    archive_minimale(tmp_path / "archive-2007.zip", XML_SALE)
    connexion = ouvrir(base)
    try:
        with connexion.transaction(), connexion.cursor() as curseur:
            curseur.execute(
                """
                INSERT INTO marts.dim_station
                    (id, geom, cp, adresse, ville, code_departement,
                     premiere_vue, derniere_vue, active)
                VALUES (1000001, ST_SetSRID(ST_MakePoint(5.19791, 46.20114), 4326)::geography,
                        '01000', '16 rue chateaubriand', 'Bourg-en-Bresse', '01',
                        %s, %s, true)
                """,
                (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), dt.datetime(2026, 11, 1, tzinfo=dt.UTC)),
            )
        backfill.amorcer(connexion, 2007, repertoire=tmp_path, user_agent="tests")
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT adresse, active, premiere_vue FROM marts.dim_station WHERE id = 1000001"
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert ligne is not None
    adresse, active, premiere_vue = ligne
    assert adresse == "16 rue chateaubriand", "l adresse a jour ne doit pas etre ecrasee"
    assert active is True, "une station vivante ne doit pas etre desactivee par l archive"
    assert premiere_vue == dt.datetime(2007, 1, 1, tzinfo=dt.UTC), (
        "la premiere vue doit reculer dans le passe"
    )


@pytest.mark.integration
@sans_base
def test_une_station_que_seule_l_archive_connait_est_creee_inactive(
    base: str, tmp_path: Path
) -> None:
    """Fermee depuis : son historique existe, mais elle ne sort d'aucune recherche."""
    archive_minimale(tmp_path / "archive-2007.zip", XML_SALE)
    connexion = ouvrir(base)
    try:
        resultat = backfill.amorcer(connexion, 2007, repertoire=tmp_path, user_agent="tests")
        with connexion.cursor() as curseur:
            curseur.execute("SELECT active, code_departement FROM marts.dim_station")
            lignes = curseur.fetchall()
    finally:
        connexion.close()
    assert resultat.stations_creees == 1
    assert lignes == [(False, "01")]
