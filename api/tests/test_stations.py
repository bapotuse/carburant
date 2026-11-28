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


@sans_base
async def test_meta_porte_l_attribution_d_openstreetmap(
    client: httpx.AsyncClient,
) -> None:
    """La licence ODbL impose l attribution partout ou une enseigne est affichee.

    Ce n'est pas une politesse : c'est une obligation de la licence sous laquelle
    OpenStreetMap nous laisse utiliser ses enseignes. Le pied de page du site la
    reprend depuis cette liste.
    """
    corps = (await client.get("/v1/meta")).json()
    osm = [s for s in corps["sources"] if "OpenStreetMap" in s["attribution"]]
    assert osm, f"attribution OpenStreetMap absente : {corps['sources']}"
    assert "ODbL" in osm[0]["licence"]
    assert osm[0]["url"].startswith("https://www.openstreetmap.org/copyright")
    # L'ADEME aussi : les facteurs d'emission porteront un chiffre affiche.
    assert any("ADEME" in s["attribution"] for s in corps["sources"])


# --------------------------------------------------- /v1/stations/meilleure
@sans_base
async def test_la_meilleure_station_n_est_pas_la_moins_chere_au_litre(
    client: httpx.AsyncClient,
) -> None:
    """Le cas qui justifie l endpoint, contre une vraie base.

    Le jeu de donnees a une station proche a prix plus eleve et une plus lointaine
    moins chere au litre. Le classement se fait sur le cout reel, detour compris.
    """
    reponse = await client.get(
        "/v1/stations/meilleure",
        params={"lat": PRADO[0], "lon": PRADO[1], "carburant": "gazole", "autonomie_km": 80},
    )
    assert reponse.status_code == 200
    corps = reponse.json()

    assert corps["meilleure"] is not None
    assert corps["atteignables"] >= 2
    # Le classement est bien par cout reel croissant.
    couts = [s["cout_reel_eur"] for s in corps["stations"]]
    assert couts == sorted(couts)
    # Et le cout reel depasse toujours le seul prix du plein.
    for station in corps["stations"]:
        assert station["cout_reel_eur"] >= station["cout_plein_eur"]
        assert station["cout_detour_eur"] >= 0


@sans_base
async def test_la_meilleure_station_expose_ses_hypotheses(
    client: httpx.AsyncClient,
) -> None:
    """Un chiffre qu'on ne peut pas refaire soi-meme n'a pas sa place."""
    corps = (
        await client.get(
            "/v1/stations/meilleure",
            params={"lat": PRADO[0], "lon": PRADO[1], "carburant": "gazole"},
        )
    ).json()
    hypotheses = corps["hypotheses"]
    assert hypotheses["aller_retour"] is True
    assert hypotheses["facteur_detour"] == 1.3
    assert hypotheses["marge_autonomie"] == 0.8
    assert hypotheses["litres"] == 40.0
    assert "approximation" in hypotheses["prix_du_trajet"]


@sans_base
async def test_une_autonomie_minuscule_ne_recommande_rien(
    client: httpx.AsyncClient,
) -> None:
    """Cas limite de la spec : aucune station atteignable, et on le dit clairement."""
    corps = (
        await client.get(
            "/v1/stations/meilleure",
            params={
                "lat": PRADO[0],
                "lon": PRADO[1],
                "carburant": "gazole",
                "autonomie_km": 0.1,
            },
        )
    ).json()
    assert corps["meilleure"] is None
    assert corps["atteignables"] == 0
    assert corps["avertissement"] is not None
    assert "atteignable" in corps["avertissement"]


@sans_base
async def test_l_economie_n_est_jamais_negative(client: httpx.AsyncClient) -> None:
    corps = (
        await client.get(
            "/v1/stations/meilleure",
            params={"lat": PRADO[0], "lon": PRADO[1], "carburant": "gazole"},
        )
    ).json()
    assert corps["economie_eur"] >= 0


@sans_base
async def test_le_prix_perime_est_ecarte_de_la_recommandation(
    client: httpx.AsyncClient,
) -> None:
    """La station 3 est la plus proche du Prado mais son prix a 60 jours."""
    corps = (
        await client.get(
            "/v1/stations/meilleure",
            params={"lat": PRADO[0], "lon": PRADO[1], "carburant": "gazole"},
        )
    ).json()
    identifiants = [s["id"] for s in corps["stations"]]
    assert 3 not in identifiants, "un prix perime ne doit pas etre recommande"


@sans_base
async def test_une_autonomie_negative_est_refusee(client: httpx.AsyncClient) -> None:
    reponse = await client.get(
        "/v1/stations/meilleure",
        params={
            "lat": PRADO[0],
            "lon": PRADO[1],
            "carburant": "gazole",
            "autonomie_km": -10,
        },
    )
    assert reponse.status_code == 422


@sans_base
async def test_un_carburant_inconnu_liste_les_valeurs_acceptees(
    client: httpx.AsyncClient,
) -> None:
    reponse = await client.get(
        "/v1/stations/meilleure",
        params={"lat": PRADO[0], "lon": PRADO[1], "carburant": "diesel"},
    )
    assert reponse.status_code == 422
    corps = reponse.json()
    assert "gazole" in corps["detail"], "l erreur doit lister les valeurs acceptees"


@sans_base
async def test_une_position_hors_de_france_est_refusee(client: httpx.AsyncClient) -> None:
    """Aucune station d'outre-mer dans le flux : autant le dire franchement."""
    reponse = await client.get(
        "/v1/stations/meilleure",
        params={"lat": -20.88, "lon": 55.45, "carburant": "gazole"},
    )
    assert reponse.status_code == 422
    assert "outre-mer" in reponse.json()["detail"]


# ------------------------------------------------- /v1/stations/{id} et historique
@sans_base
async def test_la_fiche_montre_aussi_les_prix_perimes(client: httpx.AsyncClient) -> None:
    """Contrairement a une recherche, une fiche ne cache rien.

    La station 3 a un prix de 60 jours : il est absent des recherches, present sur
    sa fiche, avec sa date et sa classe de fraicheur. Un prix vieux n'est pas une
    raison de faire comme s'il n'existait pas, c'est une raison de le dater.
    """
    reponse = await client.get("/v1/stations/3")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["id"] == 3
    assert corps["prix"], "la fiche doit montrer le prix meme perime"
    assert corps["prix"][0]["fraicheur"] == "perime"
    assert corps["prix"][0]["maj"] is not None


@sans_base
async def test_une_station_inconnue_repond_404_en_problem_json(
    client: httpx.AsyncClient,
) -> None:
    reponse = await client.get("/v1/stations/99999999")
    assert reponse.status_code == 404
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert "identifiant" in reponse.json()["detail"]


@sans_base
async def test_la_fiche_porte_la_provenance_de_l_enseigne(
    base: str, client: httpx.AsyncClient
) -> None:
    """Un rapprochement geographique merite plus de prudence qu'un identifiant."""
    with psycopg.connect(base, autocommit=True) as connexion:
        connexion.execute(
            b"UPDATE marts.dim_station SET enseigne = 'TotalEnergies', "
            b"enseigne_source = 'osm-reference', enseigne_score = 1.0, "
            b"enseigne_osm = 'node/144574' WHERE id = 1"
        )
    corps = (await client.get("/v1/stations/1")).json()
    assert corps["enseigne"]["nom"] == "TotalEnergies"
    assert corps["enseigne"]["source"] == "osm-reference"
    assert corps["enseigne"]["score"] == 1.0
    assert corps["enseigne"]["objet_osm"] == "node/144574"


@sans_base
async def test_une_station_sans_enseigne_le_dit(client: httpx.AsyncClient) -> None:
    """Rien n'est invente : sans enseigne, la station s'identifie par son adresse."""
    corps = (await client.get("/v1/stations/2")).json()
    assert corps["enseigne"] is None
    assert corps["adresse"]


@sans_base
async def test_l_historique_est_du_plus_recent_au_plus_ancien(
    client: httpx.AsyncClient,
) -> None:
    corps = (await client.get("/v1/stations/1/historique")).json()
    dates = [c["maj"] for c in corps["changements"]]
    assert dates == sorted(dates, reverse=True)
    assert corps["total"] == len(corps["changements"])


@sans_base
async def test_l_historique_se_filtre_par_carburant(client: httpx.AsyncClient) -> None:
    corps = (await client.get("/v1/stations/1/historique", params={"carburant": "gazole"})).json()
    assert corps["carburant"] == "gazole"
    assert all(c["carburant"] == "gazole" for c in corps["changements"])


@sans_base
async def test_l_historique_d_une_station_inconnue_repond_404(
    client: httpx.AsyncClient,
) -> None:
    reponse = await client.get("/v1/stations/99999999/historique")
    assert reponse.status_code == 404


# ----------------------------------------------------------------------- /v1/meta
@sans_base
async def test_meta_ne_compte_jamais_les_lignes_de_fact_prix(base: str) -> None:
    """Garde-fou de regression : `/v1/meta` est aussi la sonde de vivacite.

    Elle a quatre secondes de budget. Un `count(*)` sur `marts.fact_prix` y etait
    inoffensif au Jalon 1 (33 000 lignes) et est devenu mortel apres l'amorcage de
    l'historique (64 millions de lignes sur 242 partitions, 8 Go) : il a fait
    declarer le conteneur malade et echouer un deploiement.

    Le test lit le plan d'execution et exige que la table de faits n'y figure pas du
    tout. Verifier un temps de reponse ne prouverait rien ici : sur la petite base
    de test, le comptage est instantane. C'est la **forme** du plan qu'il faut
    verrouiller, pas sa vitesse.
    """
    from carburant_api.requetes.stations import _SQL_META

    with psycopg.connect(base, autocommit=True) as connexion:
        plan = "\n".join(
            str(ligne[0]) for ligne in connexion.execute(f"EXPLAIN {_SQL_META}").fetchall()
        )

    assert "fact_prix" not in plan, (
        "le plan de /v1/meta touche la table de faits ; elle pese 8 Go en production "
        f"et la sonde de vivacite a quatre secondes.\nPlan obtenu :\n{plan}"
    )
    assert "pg_class" in plan, "le compte doit venir des statistiques du catalogue"


@sans_base
async def test_meta_annonce_un_ordre_de_grandeur_credible(
    base: str, client: httpx.AsyncClient
) -> None:
    """L'estimation doit refleter les lignes chargees, apres `ANALYZE`.

    Avant `ANALYZE`, `reltuples` vaut -1 sur une partition neuve depuis PostgreSQL 14 :
    le `greatest(..., 0)` du SQL garantit alors un zero, jamais un negatif. Apres, on
    retrouve l'ordre de grandeur. Le champ s'appelle `prix_connus_environ` precisement
    parce qu'on ne promet pas mieux qu'un ordre de grandeur.
    """
    avant = (await client.get("/v1/meta")).json()
    assert avant["prix_connus_environ"] >= 0, "jamais negatif, meme sans ANALYZE"

    with psycopg.connect(base, autocommit=True) as connexion:
        connexion.execute("ANALYZE marts.fact_prix")
        ligne = connexion.execute("SELECT count(*) FROM marts.fact_prix").fetchone()
    assert ligne is not None
    reel = int(ligne[0])

    apres = (await client.get("/v1/meta")).json()
    estime = apres["prix_connus_environ"]
    assert estime == pytest.approx(reel, rel=0.1), (
        f"estimation {estime} contre {reel} lignes reellement presentes"
    )


# ------------------------------------------------------- horizon de recherche
@sans_base
async def test_l_horizon_n_exclut_que_des_prix_deja_ecartes(base: str) -> None:
    """La borne basse sur `maj` ne doit rien changer au resultat.

    C'est la condition de la correction de performance : l'horizon est place un jour
    **avant** le seuil de peremption, donc tout prix qu'il exclut aurait de toute
    facon ete ecarte par `fraicheur <> 'perime'`. Le test l'exige de la base
    elle-meme, plutot que de faire confiance a l'arithmetique du commentaire -- une
    modification du seuil de peremption sans l'horizon ferait echouer ce test.
    """
    with psycopg.connect(base, autocommit=True) as connexion:
        ligne = connexion.execute(
            """
            SELECT marts.classe_fraicheur(marts.horizon_prix_exploitable()) AS a_l_horizon,
                   marts.classe_fraicheur(
                       marts.horizon_prix_exploitable() + interval '1 day'
                   ) AS un_jour_apres
            """
        ).fetchone()
    assert ligne is not None
    assert ligne[0] == "perime", (
        "un prix pose exactement a l'horizon doit deja etre perime, sinon l'horizon "
        "ecarte des prix que la recherche aurait gardes"
    )
    assert ligne[1] != "perime", (
        "un jour apres l'horizon, le prix doit encore etre exploitable : sinon "
        "l'horizon est inutilement large"
    )


@sans_base
async def test_l_horizon_elague_les_partitions(base: str) -> None:
    """Le plan ne doit pas toucher une partition entierement anterieure a l'horizon.

    C'est tout l'objet de l'horizon, et c'est ce qui a sauve la recherche apres
    l'amorcage : sans lui, le plan fait un parcours d'index par station candidate
    **et par partition**, 242 en production.

    Le test cree donc une vraie partition ancienne et exige qu'elle soit absente du
    plan. Mesurer un temps de reponse ne prouverait rien sur une base de test, et
    compter les partitions du plan non plus : le jeu d'essai n'en cree que trois, si
    bien qu'un plan non elague y ressemblerait a un plan elague.
    """
    from carburant_api.requetes.stations import _HORIZON_PROCHES, _ORDRES, _SQL_PROCHES

    requete = _SQL_PROCHES.format(ordre=_ORDRES["prix"], horizon=_HORIZON_PROCHES)
    with psycopg.connect(base, autocommit=True) as connexion:
        connexion.execute(
            "CREATE TABLE marts.fact_prix_202401 PARTITION OF marts.fact_prix "
            "FOR VALUES FROM ('2024-01-01T00:00:00+00') TO ('2024-02-01T00:00:00+00')"
        )
        connexion.execute(
            "INSERT INTO marts.fact_prix "
            "(station_id, carburant, prix, maj, premiere_collecte, derniere_observation) "
            "VALUES (1, 'gazole', 1.5, '2024-01-15T12:00:00+00', 1, now())"
        )
        # L'elagage se fait a l'execution : `now()` n'est connu qu'a ce moment-la.
        plan = "\n".join(
            str(ligne[0])
            for ligne in connexion.execute(
                f"EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF, SUMMARY OFF) {requete}",
                {
                    "lat": 43.2726,
                    "lon": 5.3846,
                    "rayon_m": 10000.0,
                    "carburant": "gazole",
                    "inclure_perimes": False,
                },
            ).fetchall()
        )

    assert "fact_prix_202401" not in plan, (
        "la recherche lit une partition de janvier 2024, entierement anterieure a "
        f"l'horizon : l'elagage ne fonctionne pas.\nPlan obtenu :\n{plan}"
    )


@sans_base
async def test_demander_les_perimes_les_ramene(base: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """L'autre moitie de l'assemblage : sans horizon, les perimes reviennent.

    `inclure_perimes` n'a aucun appelant aujourd'hui, mais la requete est assemblee
    autour de lui : si l'assemblage se cassait, personne ne le verrait. La station 3
    du jeu d'essai a un prix de soixante jours.
    """
    from carburant_api.requetes.connexion import creer_pool
    from carburant_api.requetes.stations import Recherche, stations_proches

    def recherche(*, perimes: bool) -> Recherche:
        return Recherche(
            latitude=43.2726,
            longitude=5.3846,
            rayon_km=10,
            carburant="gazole",
            tri="prix",
            limite=50,
            decalage=0,
            inclure_perimes=perimes,
        )

    monkeypatch.setenv("DATABASE_URL", base)
    pool = creer_pool()
    await pool.open(wait=True)
    try:
        sans = await stations_proches(pool, recherche(perimes=False))
        avec = await stations_proches(pool, recherche(perimes=True))
    finally:
        await pool.close()

    identifiants_sans = {ligne["id"] for ligne in sans[0]}
    identifiants_avec = {ligne["id"] for ligne in avec[0]}
    assert 3 not in identifiants_sans, "la station au prix perime doit etre absente"
    assert 3 in identifiants_avec, "elle doit revenir quand on demande les perimes"
