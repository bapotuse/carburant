"""`/v1/stations/proches`, contre une vraie base PostGIS.

Les regles qui comptent ici ne se verifient qu'avec PostGIS et de vraies partitions :
la distance geographique, le tri, l'exclusion des prix perimes, celle des carburants
en rupture, et le fait qu'un prix n'arrive jamais sans sa date.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import psycopg
import pytest
from carburant_api.app import creer_app

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")

# Le Prado, a Marseille : le point de reference de tout le projet.
PRADO = (43.2726, 5.3846)


def _sql_jeu_de_donnees(maintenant: dt.datetime) -> str:
    """Un petit jeu de stations autour du Prado, aux distances connues."""
    frais = (maintenant - dt.timedelta(hours=2)).isoformat()
    ancien = (maintenant - dt.timedelta(days=10)).isoformat()
    perime = (maintenant - dt.timedelta(days=60)).isoformat()
    return f"""
    INSERT INTO marts.dim_station
        (id, geom, adresse, ville, cp, departement, code_departement,
         autoroute, premiere_vue, derniere_vue, active)
    VALUES
      -- ~0,6 km du Prado, gazole le moins cher
      (1, ST_SetSRID(ST_MakePoint(5.3846, 43.2780), 4326)::geography,
       'Proche et pas chere', 'Marseille', '13008', 'Bouches-du-Rhone', '13',
       false, '{frais}', '{frais}', true),
      -- ~2,2 km, gazole plus cher
      (2, ST_SetSRID(ST_MakePoint(5.4100, 43.2726), 4326)::geography,
       'Un peu plus loin', 'Marseille', '13010', 'Bouches-du-Rhone', '13',
       false, '{frais}', '{frais}', true),
      -- ~0,3 km mais prix perime : doit disparaitre des recherches
      (3, ST_SetSRID(ST_MakePoint(5.3846, 43.2753), 4326)::geography,
       'Prix oublie', 'Marseille', '13008', 'Bouches-du-Rhone', '13',
       false, '{perime}', '{frais}', true),
      -- ~0,9 km, gazole en rupture : doit disparaitre des recherches gazole
      (4, ST_SetSRID(ST_MakePoint(5.3900, 43.2800), 4326)::geography,
       'En rupture', 'Marseille', '13008', 'Bouches-du-Rhone', '13',
       false, '{frais}', '{frais}', true),
      -- station inactive : ne doit jamais sortir
      (5, ST_SetSRID(ST_MakePoint(5.3850, 43.2730), 4326)::geography,
       'Fermee', 'Marseille', '13008', 'Bouches-du-Rhone', '13',
       false, '{frais}', '{frais}', false),
      -- a 40 km : hors d'un rayon de 10 km
      (6, ST_SetSRID(ST_MakePoint(5.8000, 43.2726), 4326)::geography,
       'Trop loin', 'Aubagne', '13400', 'Bouches-du-Rhone', '13',
       false, '{frais}', '{frais}', true);

    INSERT INTO marts.fact_prix
        (station_id, carburant, prix, maj, premiere_collecte, derniere_observation)
    VALUES
      (1, 'gazole', 1.799, '{frais}',  1, '{frais}'),
      (1, 'e10',    1.699, '{frais}',  1, '{frais}'),
      (2, 'gazole', 1.999, '{frais}',  1, '{frais}'),
      (3, 'gazole', 1.499, '{perime}', 1, '{frais}'),
      (4, 'gazole', 1.599, '{frais}',  1, '{frais}'),
      (5, 'gazole', 1.299, '{frais}',  1, '{frais}'),
      (6, 'gazole', 1.399, '{frais}',  1, '{frais}'),
      -- prix ancien (10 jours) : garde, mais etiquete
      (2, 'e10',    1.749, '{ancien}', 1, '{frais}');

    INSERT INTO marts.rupture (station_id, carburant, type, debut, derniere_vue)
    VALUES (4, 'gazole', 'temporaire', '{frais}', '{frais}');
    """


@pytest.fixture
def base() -> Iterator[str]:
    """Base jetable, migrations appliquees, jeu de donnees charge."""
    from carburant_etl.chargement.marts import assurer_partitions
    from carburant_etl.chargement.migrations import appliquer

    assert URL
    nom = f"carburant_api_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(URL, autocommit=True) as administration:
        administration.execute(f'CREATE DATABASE "{nom}"')
    url_test = URL.rsplit("/", 1)[0] + f"/{nom}"
    try:
        appliquer(url_test)
        maintenant = dt.datetime.now(tz=dt.UTC)
        with psycopg.connect(url_test, autocommit=True) as connexion:
            mois = set()
            for jours in (0, 1, 11, 61):
                date = maintenant - dt.timedelta(days=jours)
                mois.add((date.year, date.month))
            assurer_partitions(connexion, mois)
            connexion.execute(_sql_jeu_de_donnees(maintenant).encode())
        yield url_test
    finally:
        with psycopg.connect(URL, autocommit=True) as administration:
            administration.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nom,),
            )
            administration.execute(f'DROP DATABASE IF EXISTS "{nom}"')


@pytest.fixture
async def client(base: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """Un client qui parle a l'application, branchee sur la base jetable."""
    monkeypatch.setenv("DATABASE_URL", base)
    app = creer_app()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as cliente,
    ):
        yield cliente


async def proches(cliente: httpx.AsyncClient, **params: str | float) -> dict[str, Any]:
    defauts: dict[str, str] = {
        "lat": str(PRADO[0]),
        "lon": str(PRADO[1]),
        "rayon_km": "10",
    }
    defauts.update({cle: str(valeur) for cle, valeur in params.items()})
    reponse = await cliente.get("/v1/stations/proches", params=defauts)
    assert reponse.status_code == 200, reponse.text
    corps: dict[str, Any] = reponse.json()
    return corps


# ---------------------------------------------------------------- recherche


@sans_base
async def test_les_stations_sortent_triees_par_prix(client: httpx.AsyncClient) -> None:
    corps = await proches(client, carburant="gazole")
    identifiants = [s["id"] for s in corps["stations"]]
    # 1 (1,799) puis 2 (1,999). La 3 est perimee, la 4 en rupture, la 5 inactive,
    # la 6 hors rayon.
    assert identifiants == [1, 2]
    prix = [s["prix"][0]["prix_eur_l"] for s in corps["stations"]]
    assert prix == sorted(prix)


@sans_base
async def test_le_tri_par_distance_change_l_ordre(client: httpx.AsyncClient) -> None:
    corps = await proches(client, carburant="gazole", tri="distance")
    distances = [s["distance_km"] for s in corps["stations"]]
    assert distances == sorted(distances)


@sans_base
async def test_un_prix_perime_est_exclu_des_recherches(
    client: httpx.AsyncClient,
) -> None:
    """La station 3 est la plus proche et la moins chere, mais son prix a 60 jours."""
    corps = await proches(client, carburant="gazole")
    assert 3 not in [s["id"] for s in corps["stations"]]


@sans_base
async def test_un_carburant_en_rupture_est_exclu(client: httpx.AsyncClient) -> None:
    """La station 4 a un gazole a 1,599 EUR, mais il est declare en rupture."""
    corps = await proches(client, carburant="gazole")
    assert 4 not in [s["id"] for s in corps["stations"]]


@sans_base
async def test_une_station_inactive_n_apparait_jamais(
    client: httpx.AsyncClient,
) -> None:
    corps = await proches(client, carburant="gazole")
    assert 5 not in [s["id"] for s in corps["stations"]]


@sans_base
async def test_le_rayon_est_respecte(client: httpx.AsyncClient) -> None:
    proche = await proches(client, carburant="gazole", rayon_km=1)
    large = await proches(client, carburant="gazole", rayon_km=50)
    assert [s["id"] for s in proche["stations"]] == [1]
    assert 6 in [s["id"] for s in large["stations"]]


@sans_base
async def test_sans_carburant_toutes_les_pompes_sortent(
    client: httpx.AsyncClient,
) -> None:
    corps = await proches(client)
    station_1 = next(s for s in corps["stations"] if s["id"] == 1)
    assert {p["carburant"] for p in station_1["prix"]} == {"gazole", "e10"}


# ---------------------------------------------------------------- fraicheur


@sans_base
async def test_un_prix_ancien_est_garde_mais_etiquete(
    client: httpx.AsyncClient,
) -> None:
    """Ecarter un prix de 10 jours priverait l'utilisateur d'une station qui existe."""
    corps = await proches(client, carburant="e10")
    station_2 = next(s for s in corps["stations"] if s["id"] == 2)
    assert station_2["prix"][0]["fraicheur"] == "ancien"


@sans_base
async def test_un_prix_n_arrive_jamais_sans_sa_date(
    client: httpx.AsyncClient,
) -> None:
    """La regle la plus importante du projet."""
    corps = await proches(client)
    for station in corps["stations"]:
        for prix in station["prix"]:
            if prix["prix_eur_l"] is not None:
                assert prix["maj"] is not None, station
                assert prix["fraicheur"] is not None, station


# ---------------------------------------------------------------- distances


@sans_base
async def test_les_distances_sont_en_kilometres_et_plausibles(
    client: httpx.AsyncClient,
) -> None:
    corps = await proches(client, carburant="gazole")
    station_1 = next(s for s in corps["stations"] if s["id"] == 1)
    station_2 = next(s for s in corps["stations"] if s["id"] == 2)
    # 0,0054 degre de latitude, soit environ 600 m.
    assert 0.4 < station_1["distance_km"] < 0.8
    # 0,0254 degre de longitude a cette latitude, soit environ 2 km.
    assert 1.8 < station_2["distance_km"] < 2.4


# ---------------------------------------------------------------- erreurs


@sans_base
async def test_un_carburant_inconnu_renvoie_un_probleme_exploitable(
    client: httpx.AsyncClient,
) -> None:
    reponse = await client.get(
        "/v1/stations/proches",
        params={"lat": PRADO[0], "lon": PRADO[1], "carburant": "diesel"},
    )
    assert reponse.status_code == 422
    assert reponse.headers["content-type"].startswith("application/problem+json")
    corps = reponse.json()
    # L'erreur doit lister les valeurs acceptees : un modele de langage la relaie.
    assert "gazole" in corps["detail"]
    assert corps["carburants_acceptes"] == [
        "gazole",
        "sp95",
        "e10",
        "sp98",
        "e85",
        "gplc",
    ]


@sans_base
async def test_une_position_hors_de_france_le_dit_franchement(
    client: httpx.AsyncClient,
) -> None:
    """Le flux ne contient aucune station d'outre-mer : autant le dire."""
    reponse = await client.get("/v1/stations/proches", params={"lat": 14.6, "lon": -61.0})
    assert reponse.status_code == 422
    assert "outre-mer" in reponse.json()["detail"]


@sans_base
async def test_un_rayon_absurde_est_refuse(client: httpx.AsyncClient) -> None:
    reponse = await client.get(
        "/v1/stations/proches",
        params={"lat": PRADO[0], "lon": PRADO[1], "rayon_km": 500},
    )
    assert reponse.status_code == 422
    assert "rayon_km" in reponse.json()["detail"]


# ---------------------------------------------------------------- cache


@sans_base
async def test_les_entetes_de_cache_sont_poses(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/v1/stations/proches", params={"lat": PRADO[0], "lon": PRADO[1]})
    assert reponse.headers["cache-control"].startswith("public, max-age=")
    assert reponse.headers["etag"].startswith('"')


@sans_base
async def test_deux_requetes_identiques_donnent_le_meme_etag(
    client: httpx.AsyncClient,
) -> None:
    params: dict[str, str] = {
        "lat": str(PRADO[0]),
        "lon": str(PRADO[1]),
        "carburant": "gazole",
    }
    premiere = await client.get("/v1/stations/proches", params=params)
    seconde = await client.get("/v1/stations/proches", params=params)
    assert premiere.headers["etag"] == seconde.headers["etag"]


# ---------------------------------------------------------------- meta


@sans_base
async def test_meta_annonce_la_couverture_et_ses_limites(
    client: httpx.AsyncClient,
) -> None:
    reponse = await client.get("/v1/meta")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["stations_actives"] == 5
    assert "outre-mer" in corps["couverture"]
    assert any("Etalab" in s["licence"] for s in corps["sources"])
