"""Enseignes OpenStreetMap : lecture de la reponse Overpass et rapprochement.

Les trois exemples servant de base a ces tests sont **de vrais elements** rapportes
par la reconnaissance du 26/11/2026 (`docs/reconnaissance.md` § 6), recopies sans
retouche : un Eni d'aire d'autoroute, un TotalEnergies dont le `name` designe la
station et non l'enseigne, un Dyneff sans code postal.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from carburant_etl.chargement.enseignes import SCORE_SPATIAL_MAX, rapprocher
from carburant_etl.chargement.migrations import appliquer
from carburant_etl.chargement.staging import ouvrir
from carburant_etl.sources import osm

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")


ENI = {
    "type": "node",
    "id": 144574,
    "lat": 47.3098325,
    "lon": 4.5013158,
    "tags": {
        "amenity": "fuel",
        "brand": "Eni",
        "brand:wikidata": "Q565594",
        "name": "Eni",
        "ref:FR:prix-carburants": "21320007",
    },
}

TOTAL = {
    "type": "node",
    "id": 10350952,
    "lat": 46.9650397,
    "lon": 4.8361985,
    "tags": {
        "amenity": "fuel",
        "brand": "TotalEnergies",
        "brand:wikidata": "Q154037",
        # Le `name` designe la station, pas l'enseigne : d'ou la priorite de `brand`.
        "name": "Relais Beaune Tailly (PL)",
        "operator": "TotalEnergies",
        "ref:FR:prix-carburants": "21200009",
    },
}

SURFACE = {
    "type": "way",
    "id": 987654,
    "center": {"lat": 43.2700000, "lon": 5.3900000},
    "tags": {"amenity": "fuel", "brand": "Avia"},
}


# ------------------------------------------------------------------- la lecture
def test_le_libelle_privilegie_brand_sur_name() -> None:
    """« Relais Beaune Tailly (PL) » est une station, « TotalEnergies » une enseigne."""
    points = osm.lire_elements([TOTAL])
    assert len(points) == 1
    assert points[0].enseigne == "TotalEnergies"
    assert points[0].wikidata == "Q154037"


def test_name_sert_quand_brand_manque() -> None:
    element: dict[str, Any] = {
        "type": "node",
        "id": 1,
        "lat": 48.0,
        "lon": 2.0,
        "tags": {"amenity": "fuel", "name": "Station du Centre"},
    }
    assert osm.lire_elements([element])[0].enseigne == "Station du Centre"


def test_une_surface_a_une_position_grace_a_out_center() -> None:
    """4 478 des 12 610 elements sont des `way` : sans leur centre, on en perdrait 36 %."""
    points = osm.lire_elements([SURFACE])
    assert len(points) == 1
    assert points[0].cle == "way/987654"
    assert points[0].latitude == pytest.approx(43.27)


def test_un_element_sans_rien_d_exploitable_est_ecarte() -> None:
    """Ni enseigne ni reference : OSM connait mal cette station, ce n'est pas une anomalie."""
    element: dict[str, Any] = {"type": "node", "id": 2, "lat": 48.0, "lon": 2.0, "tags": {}}
    assert osm.lire_elements([element]) == []


def test_la_reference_officielle_est_lue() -> None:
    points = osm.lire_elements([ENI])
    assert points[0].reference_officielle == "21320007"


# ------------------------------------------------------------------ le transport
def client_rendant(elements: list[dict[str, Any]], *, statut: int = 200) -> httpx.MockTransport:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(statut, json={"elements": elements})

    return httpx.MockTransport(gestionnaire)


def test_une_reponse_tronquee_est_refusee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overpass tronque sans erreur quand il est charge : une reponse courte ment."""
    monkeypatch.setattr(osm, "RECUL_SECONDES", 0.0)
    with (
        httpx.Client(transport=client_rendant([ENI] * 10)) as client,
        pytest.raises(osm.SourceOsmIndisponible, match="elements seulement"),
    ):
        osm.recuperer("tests", miroirs=("https://exemple/interpreter",), client=client)


def test_le_miroir_suivant_prend_le_relais(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'instance principale refuse parfois puis accepte : essayer ailleurs vaut mieux."""
    monkeypatch.setattr(osm, "RECUL_SECONDES", 0.0)
    monkeypatch.setattr(osm, "ATTENDUS_MINIMUM", 2)
    appels: list[str] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(str(requete.url))
        if "premier" in str(requete.url):
            raise httpx.ConnectError("connexion refusee")
        return httpx.Response(200, json={"elements": [ENI, TOTAL, SURFACE]})

    with httpx.Client(transport=httpx.MockTransport(gestionnaire)) as client:
        points = osm.recuperer(
            "tests",
            miroirs=("https://premier/interpreter", "https://second/interpreter"),
            client=client,
        )
    assert len(points) == 3
    assert sum(1 for a in appels if "premier" in a) == osm.TENTATIVES_PAR_MIROIR


# --------------------------------------------------------------- le rapprochement
@pytest.fixture
def base() -> Iterator[str]:
    assert URL
    nom = f"carburant_enseignes_{uuid.uuid4().hex[:12]}"
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


def poser_station(
    connexion: psycopg.Connection[tuple[object, ...]],
    identifiant: int,
    longitude: float,
    latitude: float,
) -> None:
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO marts.dim_station (id, geom, premiere_vue, derniere_vue, active)
            VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, now(), now(), true)
            """,
            (identifiant, longitude, latitude),
        )


@pytest.mark.integration
@sans_base
def test_l_identifiant_officiel_l_emporte_sur_la_distance(base: str) -> None:
    """Une station a 500 m de son point OSM est quand meme rapprochee, par la cle.

    C'est tout l'interet du tag `ref:FR:prix-carburants` : la geographie peut etre
    approximative des deux cotes, l'identifiant ne l'est pas.
    """
    connexion = ouvrir(base)
    try:
        # La station est a ~800 m du point OSM : hors de tout rayon spatial.
        poser_station(connexion, 21320007, 4.5113158, 47.3098325)
        resultat = rapprocher(connexion, osm.lire_elements([ENI]))
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT enseigne, enseigne_source, enseigne_score, enseigne_osm, "
                "enseigne_wikidata FROM marts.dim_station WHERE id = 21320007"
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert resultat.par_reference == 1
    assert resultat.par_distance == 0
    assert ligne is not None
    assert ligne[0] == "Eni"
    assert ligne[1] == "osm-reference"
    assert float(ligne[2]) == 1.0  # type: ignore[arg-type]
    assert ligne[3] == "node/144574"
    assert ligne[4] == "Q565594"


@pytest.mark.integration
@sans_base
def test_le_rapprochement_spatial_sert_de_filet(base: str) -> None:
    """Sans identifiant, on rapproche par la distance, avec un score degrade."""
    connexion = ouvrir(base)
    try:
        poser_station(connexion, 13008001, 5.39, 43.27)
        resultat = rapprocher(connexion, osm.lire_elements([SURFACE]))
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT enseigne, enseigne_source, enseigne_score "
                "FROM marts.dim_station WHERE id = 13008001"
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert resultat.par_distance == 1
    assert ligne is not None
    assert ligne[0] == "Avia"
    assert ligne[1] == "osm-spatial"
    # A distance quasi nulle, le score plafonne : un rapprochement geographique ne
    # vaut jamais un rapprochement par identifiant.
    assert float(ligne[2]) == pytest.approx(SCORE_SPATIAL_MAX, abs=0.01)  # type: ignore[arg-type]


@pytest.mark.integration
@sans_base
def test_une_station_trop_loin_reste_sans_enseigne(base: str) -> None:
    """Rien n'est invente : sans correspondance, la station s'affiche par son adresse."""
    connexion = ouvrir(base)
    try:
        # 5,40 au lieu de 5,39 : environ 800 m, bien au-dela du rayon de 150 m.
        poser_station(connexion, 13008002, 5.40, 43.27)
        resultat = rapprocher(connexion, osm.lire_elements([SURFACE]))
        with connexion.cursor() as curseur:
            curseur.execute("SELECT enseigne FROM marts.dim_station WHERE id = 13008002")
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert resultat.par_distance == 0
    assert ligne is not None and ligne[0] is None


@pytest.mark.integration
@sans_base
def test_un_point_osm_ne_sert_qu_une_fois(base: str) -> None:
    """Deux stations voisines ne doivent pas heriter de la meme enseigne.

    Une aire d'autoroute en contient deux a 80 m l'une de l'autre : sans cette regle,
    le meme point OSM leur serait attribue a toutes les deux.
    """
    connexion = ouvrir(base)
    try:
        poser_station(connexion, 13008003, 5.3900, 43.2700)  # a 0 m du point
        poser_station(connexion, 13008004, 5.3906, 43.2700)  # a ~50 m
        resultat = rapprocher(connexion, osm.lire_elements([SURFACE]))
        with connexion.cursor() as curseur:
            curseur.execute("SELECT count(*) FROM marts.dim_station WHERE enseigne IS NOT NULL")
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert resultat.par_distance == 1
    assert ligne is not None and ligne[0] == 1, "le point OSM a servi deux fois"


@pytest.mark.integration
@sans_base
def test_relancer_ne_double_rien_et_sait_retirer(base: str) -> None:
    """Une enseigne disparue d'OSM doit disparaitre de chez nous aussi."""
    connexion = ouvrir(base)
    try:
        poser_station(connexion, 21320007, 4.5013158, 47.3098325)
        premier = rapprocher(connexion, osm.lire_elements([ENI]))
        # Deuxieme passage : OSM ne connait plus cette station.
        second = rapprocher(connexion, osm.lire_elements([SURFACE]))
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT enseigne, enseigne_source FROM marts.dim_station WHERE id = 21320007"
            )
            ligne = curseur.fetchone()
    finally:
        connexion.close()
    assert premier.par_reference == 1
    assert second.par_reference == 0 and second.par_distance == 0
    assert ligne is not None
    assert ligne[0] is None, "l enseigne disparue d OSM doit etre retiree"
    assert ligne[1] is None


@pytest.mark.integration
@sans_base
def test_la_couverture_est_mesurable(base: str) -> None:
    """La specification demande que le taux soit mesure **et affichable**."""
    connexion = ouvrir(base)
    try:
        poser_station(connexion, 21320007, 4.5013158, 47.3098325)
        poser_station(connexion, 13008001, 5.39, 43.27)
        poser_station(connexion, 99999999, 1.0, 45.0)  # aucune correspondance
        resultat = rapprocher(connexion, osm.lire_elements([ENI, SURFACE]))
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT source, stations FROM marts.couverture_enseigne ORDER BY source"
            )
            couverture = {str(source): nombre for source, nombre in curseur.fetchall()}
    finally:
        connexion.close()
    assert resultat.stations_actives == 3
    assert resultat.couverture_pourcent == pytest.approx(66.7, abs=0.1)
    assert couverture == {"aucune": 1, "osm-reference": 1, "osm-spatial": 1}


@pytest.mark.integration
@sans_base
def test_le_classement_regroupe_sur_wikidata_et_non_sur_le_libelle(base: str) -> None:
    """« Total », « TotalEnergies » et « Total Access » sont une seule enseigne.

    C'est tout l'interet de `brand:wikidata`. Un classement bati sur le libelle
    compterait Total trois fois et le ferait passer derriere ses concurrents a tort.
    """
    variantes = [
        {
            "type": "node",
            "id": 900 + n,
            "lat": 48.0 + n / 1000,
            "lon": 2.0,
            "tags": {
                "amenity": "fuel",
                "brand": libelle,
                "brand:wikidata": "Q154037",
                "ref:FR:prix-carburants": str(70000001 + n),
            },
        }
        for n, libelle in enumerate(("Total", "TotalEnergies", "TotalEnergies", "Total Access"))
    ]
    connexion = ouvrir(base)
    try:
        for n in range(4):
            poser_station(connexion, 70000001 + n, 2.0, 48.0 + n / 1000)
        rapprocher(connexion, osm.lire_elements(variantes))
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT enseigne, enseigne_wikidata, stations "
                "FROM marts.classement_enseigne ORDER BY stations DESC"
            )
            classement = curseur.fetchall()
    finally:
        connexion.close()
    assert len(classement) == 1, f"les variantes devraient faire une seule enseigne : {classement}"
    enseigne, wikidata, stations = classement[0]
    assert wikidata == "Q154037"
    assert stations == 4
    # Le libelle retenu est le plus frequent du groupe.
    assert enseigne == "TotalEnergies"
