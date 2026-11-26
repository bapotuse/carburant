"""`/v1/tendances` et `/v1/empreinte`, contre une vraie base.

Ces deux endpoints lisent des tables calculees par l'ETL. Les tester contre des
bouchons ne dirait rien de ce qui compte : que les agregats existent, que les
facteurs d'emission portent leur provenance, et qu'un endpoint sans donnee le dit
au lieu de rendre un chiffre faux.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import psycopg
import pytest
from carburant_api.app import creer_app
from carburant_etl.fuseau import PARIS

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")


def _jeu(aujourdhui: dt.date) -> str:
    """Trois jours d'agregats et les six facteurs d'emission."""
    lignes = []
    for n, mediane in enumerate((1.879, 1.869, 1.859)):
        jour = aujourdhui - dt.timedelta(days=n)
        lignes.append(
            f"('{jour}', 'gazole', 'france', '', 8700, 106, "
            f"{mediane - 0.25}, {mediane}, {mediane + 0.005}, {mediane + 0.44}, now())"
        )
        lignes.append(
            f"('{jour}', 'gazole', 'departement', '13', 420, 7, "
            f"{mediane - 0.20}, {mediane + 0.01}, {mediane + 0.015}, {mediane + 0.30}, now())"
        )
    valeurs = ",\n      ".join(lignes)
    return f"""
    INSERT INTO marts.agregat_prix_jour
        (jour, carburant, dimension, valeur, stations, exclus,
         prix_min, prix_median, prix_moyen, prix_max, calcule_le)
    VALUES
      {valeurs};

    INSERT INTO marts.ref_facteur_emission
        (carburant, element_ademe, nom_base, nom_attribut, valeur, unite,
         localisation, statut, periode_validite, version_base, url)
    VALUES
      ('gazole', '25775', 'Gazole routier', 'B7', 3.1, 'kgCO2e/litre',
       'France continentale', 'Valide générique', 'déc-20',
       '2026-06-30T10:17:08.470Z', 'https://data.ademe.fr/...'),
      ('e85', '25766', 'Essence', 'E85', 1.11, 'kgCO2e/litre',
       'France continentale', 'Valide générique', 'déc-20',
       '2026-06-30T10:17:08.470Z', 'https://data.ademe.fr/...');
    """


@pytest.fixture
def base() -> Iterator[str]:
    from carburant_etl.chargement.migrations import appliquer

    assert URL
    nom = f"carburant_tend_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(URL, autocommit=True) as administration:
        administration.execute(f'CREATE DATABASE "{nom}"')
    url_test = URL.rsplit("/", 1)[0] + f"/{nom}"
    try:
        appliquer(url_test)
        with psycopg.connect(url_test, autocommit=True) as connexion:
            # Les journees du projet sont des journees francaises, comme les
            # agregats que cet endpoint sert.
            connexion.execute(_jeu(dt.datetime.now(tz=PARIS).date()).encode())
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
    monkeypatch.setenv("DATABASE_URL", base)
    app = creer_app()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as cliente,
    ):
        yield cliente


# ------------------------------------------------------------------ tendances
@sans_base
async def test_la_serie_nationale_sort_dans_l_ordre(client: httpx.AsyncClient) -> None:
    corps = (await client.get("/v1/tendances", params={"carburant": "gazole"})).json()
    assert corps["dimension"] == "france"
    jours = [p["jour"] for p in corps["points"]]
    assert jours == sorted(jours), "la serie doit etre chronologique"
    assert len(jours) == 3


@sans_base
async def test_la_serie_departementale_est_distincte(client: httpx.AsyncClient) -> None:
    nationale = (await client.get("/v1/tendances", params={"carburant": "gazole"})).json()
    locale = (
        await client.get("/v1/tendances", params={"carburant": "gazole", "departement": "13"})
    ).json()
    assert locale["dimension"] == "departement"
    assert locale["valeur"] == "13"
    assert locale["points"][0]["prix_median_eur_l"] != nationale["points"][0]["prix_median_eur_l"]


@sans_base
async def test_la_serie_porte_le_nombre_de_prix_ecartes(client: httpx.AsyncClient) -> None:
    """Un agregat doit dire sur quoi il ne porte pas."""
    corps = (await client.get("/v1/tendances", params={"carburant": "gazole"})).json()
    assert all(p["exclus"] >= 0 for p in corps["points"])
    assert corps["points"][0]["stations"] > 0


@sans_base
async def test_demander_deux_decoupages_est_refuse(client: httpx.AsyncClient) -> None:
    reponse = await client.get(
        "/v1/tendances",
        params={"carburant": "gazole", "departement": "13", "reseau": "autoroute"},
    )
    assert reponse.status_code == 422
    assert "decoupage" in reponse.json()["detail"]


@sans_base
async def test_un_departement_sans_donnee_rend_une_serie_vide(
    client: httpx.AsyncClient,
) -> None:
    """Pas une erreur : une absence de donnee n'est pas une panne."""
    corps = (
        await client.get("/v1/tendances", params={"carburant": "gazole", "departement": "99"})
    ).json()
    assert corps["points"] == []


# ------------------------------------------------------------------ empreinte
@sans_base
async def test_l_empreinte_multiplie_et_cite_sa_source(client: httpx.AsyncClient) -> None:
    corps = (await client.get("/v1/empreinte", params={"carburant": "gazole", "litres": 40})).json()
    assert corps["co2_kg"] == pytest.approx(124.0)
    facteur = corps["facteur"]
    assert facteur["valeur_kg_co2e_par_litre"] == 3.1
    assert facteur["unite"] == "kgCO2e/litre"
    assert facteur["libelle_ademe"] == "Gazole routier / B7"
    assert facteur["version_base"] == "2026-06-30T10:17:08.470Z"
    assert facteur["url"].startswith("https://data.ademe.fr")


@sans_base
async def test_la_comparaison_classe_du_moins_emetteur_au_plus(
    client: httpx.AsyncClient,
) -> None:
    corps = (await client.get("/v1/empreinte/comparaison", params={"litres": 40})).json()
    emissions = [e["co2_kg"] for e in corps["empreintes"]]
    assert emissions == sorted(emissions)
    assert corps["empreintes"][0]["carburant"] == "e85"


@sans_base
async def test_la_comparaison_dit_ce_qu_elle_ne_dit_pas(client: httpx.AsyncClient) -> None:
    """Comparer a volume egal n'est pas comparer a distance egale."""
    corps = (await client.get("/v1/empreinte/comparaison")).json()
    assert "distance egale" in corps["avertissement"]


@sans_base
async def test_un_carburant_sans_facteur_le_dit_au_lieu_d_inventer(
    client: httpx.AsyncClient,
) -> None:
    """Le jeu ne charge que gazole et e85 : le sp98 n'a pas de facteur.

    Mieux vaut un 503 explicite qu'un chiffre d'empreinte carbone invente.
    """
    reponse = await client.get("/v1/empreinte", params={"carburant": "sp98"})
    assert reponse.status_code == 503
    assert "etl facteurs" in reponse.json()["detail"]


@sans_base
async def test_un_carburant_inconnu_liste_les_valeurs(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/v1/empreinte", params={"carburant": "kerosene"})
    assert reponse.status_code == 422
    assert "gazole" in reponse.json()["detail"]
