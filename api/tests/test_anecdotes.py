"""`/v1/anecdotes/du-jour`, contre une vraie base.

Trois choses sont vérifiées ici, et la deuxième est celle qui compte.

1. Les seuils. Sur une base jeune, les anecdotes historiques doivent être
   **absentes et déclarées**, pas approximées.
2. **Le retrait de tendance.** Le prix du gazole est passé de 1,07 EUR à 1,86 EUR en
   seize ans. Moyenner les prix par jour de la semaine mesurerait cette hausse, pas
   l'effet du jour. Le test plante une tendance pure, sans aucun effet
   hebdomadaire, et exige que les sept écarts soient nuls — ce qu'une moyenne brute
   ne donne pas. Puis il plante un effet connu sur un seul jour et exige la valeur
   exacte que la méthode doit produire.
3. Les chiffres de l'écart du jour, du département et de l'autoroute, sur un jeu
   dont on connaît la réponse.

Les données sont synthétiques : c'est le seul endroit du projet où c'est permis, et
c'est ce qui permet de connaître la bonne réponse à l'avance.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator

import httpx
import psycopg
import pytest
from carburant_api.app import creer_app
from carburant_api.requetes.anecdotes import (
    SEMAINES_MIN_HISTORIQUE,
    STATIONS_MIN_DEPARTEMENT,
    STATIONS_MIN_FRANCE,
)
from carburant_etl.fuseau import PARIS

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")

JOURS_HISTORIQUE = 800
"""114 semaines et deux jours. Volontairement **pas** un nombre entier de semaines :
deux jours de la semaine ont donc une observation de plus que les autres, ce qui
suffit a faire mentir une moyenne brute en presence d'une tendance."""

BASE_EUR_L = 1.000
PENTE_EUR_JOUR = 0.001
"""Tendance exacte au millieme : `prix_median` est un `numeric(5,3)`, donc une pente
de 0,001 EUR par jour se stocke sans arrondi. Toute autre pente ajouterait un bruit
d'arrondi qu'il faudrait ensuite tolerer dans les assertions."""


def _agregats_historiques(effet: dict[int, float]) -> str:
    """`JOURS_HISTORIQUE` jours d'agregats nationaux : tendance pure + effet planté.

    `effet` associe un jour ISO (1 = lundi) a un ecart en euros par litre.
    """
    debut = dt.date(2020, 1, 1)
    lignes = []
    for n in range(JOURS_HISTORIQUE):
        jour = debut + dt.timedelta(days=n)
        median = BASE_EUR_L + PENTE_EUR_JOUR * n + effet.get(jour.isoweekday(), 0.0)
        lignes.append(
            f"('{jour}', 'gazole', 'france', '', 9000, 100, "
            f"{median - 0.20:.3f}, {median:.3f}, {median:.3f}, {median + 0.40:.3f}, now())"
        )
    valeurs = ",\n      ".join(lignes)
    return f"""
    INSERT INTO marts.agregat_prix_jour
        (jour, carburant, dimension, valeur, stations, exclus,
         prix_min, prix_median, prix_moyen, prix_max, calcule_le)
    VALUES
      {valeurs};
    """


def _agregats_de_la_semaine(aujourdhui: dt.date) -> str:
    """Sept jours d'agregats : France, deux departements, et les deux reseaux.

    Le `46` est le moins cher et depasse le seuil de stations ; le `75` est plus cher ;
    le `99` est le piege : moins cher que tous, mais sous le seuil de stations.
    """
    lignes = []
    for n in range(7):
        jour = aujourdhui - dt.timedelta(days=n)
        for dimension, valeur, median, stations in (
            ("france", "", 1.860, 9000),
            ("departement", "46", 1.810, STATIONS_MIN_DEPARTEMENT + 5),
            ("departement", "75", 1.920, 300),
            ("departement", "99", 1.500, STATIONS_MIN_DEPARTEMENT - 1),
            ("reseau", "autoroute", 2.090, 400),
            ("reseau", "route", 1.850, 9000),
        ):
            lignes.append(
                f"('{jour}', 'gazole', '{dimension}', '{valeur}', {stations}, 10, "
                f"{median - 0.20:.3f}, {median:.3f}, {median:.3f}, {median + 0.40:.3f}, now())"
            )
    valeurs = ",\n      ".join(lignes)
    return f"""
    INSERT INTO marts.agregat_prix_jour
        (jour, carburant, dimension, valeur, stations, exclus,
         prix_min, prix_median, prix_moyen, prix_max, calcule_le)
    VALUES
      {valeurs};
    """


def _stations_et_prix(nombre: int) -> str:
    """`nombre` stations autour de Marseille, chacune avec un prix de gazole frais.

    Les prix vont de 1,700 a 1,700 + nombre/1000 : la moins chere et la plus chere
    sont donc connues d'avance, et l'ecart aussi. Un pas de 1 millime garde tout le
    monde dans la fourchette de la detection d'atypiques, dont ce test ne parle pas.
    """
    maintenant = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    stations, prix = [], []
    for i in range(nombre):
        identifiant = 13000000 + i
        longitude = 5.38 + i * 0.0005
        stations.append(
            f"({identifiant}, ST_SetSRID(ST_MakePoint({longitude}, 43.27), 4326)::geography, "
            f"'13008', 'Marseille', 'rue {i}', '13', false, true, "
            f"'{maintenant.isoformat()}', '{maintenant.isoformat()}')"
        )
        prix.append(
            f"({identifiant}, 'gazole', {1.700 + i / 1000:.3f}, "
            f"'{maintenant.isoformat()}', 1, '{maintenant.isoformat()}')"
        )
    return f"""
    INSERT INTO marts.dim_station
        (id, geom, cp, ville, adresse, code_departement, autoroute, active,
         premiere_vue, derniere_vue)
    VALUES
      {",\n      ".join(stations)};

    INSERT INTO marts.fact_prix
        (station_id, carburant, prix, maj, premiere_collecte, derniere_observation)
    VALUES
      {",\n      ".join(prix)};
    """


def _base_vierge() -> Iterator[str]:
    from carburant_etl.chargement.migrations import appliquer

    assert URL
    nom = f"carburant_anec_{uuid.uuid4().hex[:12]}"
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


@pytest.fixture
def base_jeune() -> Iterator[str]:
    """Une semaine d'agregats et assez de stations : deux anecdotes sur quatre."""
    for url in _base_vierge():
        with psycopg.connect(url, autocommit=True) as connexion:
            connexion.execute(_stations_et_prix(STATIONS_MIN_FRANCE + 20).encode())
            connexion.execute(_agregats_de_la_semaine(dt.datetime.now(tz=PARIS).date()).encode())
            connexion.execute("REFRESH MATERIALIZED VIEW marts.reference_departementale")
        yield url


@pytest.fixture
def base_sans_rien() -> Iterator[str]:
    """Migrations appliquees, aucune donnee : les quatre anecdotes doivent manquer."""
    yield from _base_vierge()


async def _anecdotes(url: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setenv("DATABASE_URL", url)
    app = creer_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as cliente,
    ):
        reponse = await cliente.get("/v1/anecdotes/du-jour", params={"carburant": "gazole"})
        assert reponse.status_code == 200, reponse.text
        corps: dict[str, object] = reponse.json()
        return corps


# --------------------------------------------------------------------- seuils
@sans_base
async def test_une_base_vide_declare_les_quatre_anecdotes_manquantes(
    base_sans_rien: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aucune anecdote approximee : quatre absences, chacune avec sa raison."""
    corps = await _anecdotes(base_sans_rien, monkeypatch)
    indisponibles = corps["indisponibles"]
    assert isinstance(indisponibles, list)
    assert {i["cle"] for i in indisponibles} == {
        "ecart_du_jour",
        "departement_moins_cher",
        "surcout_autoroute",
        "jour_semaine_moins_cher",
    }
    for absente in indisponibles:
        assert absente["raison"], "une absence doit dire son seuil"
        assert absente["mesure"], "une absence doit dire ce qu'on a reellement"
    for cle in ("ecart_du_jour", "departement_moins_cher", "surcout_autoroute"):
        assert corps[cle] is None


@sans_base
async def test_la_base_jeune_n_a_pas_d_anecdote_historique(
    base_jeune: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une semaine de donnees ne permet pas de dire « historiquement »."""
    corps = await _anecdotes(base_jeune, monkeypatch)
    assert corps["jour_semaine_moins_cher"] is None
    indisponibles = corps["indisponibles"]
    assert isinstance(indisponibles, list)
    absente = next(i for i in indisponibles if i["cle"] == "jour_semaine_moins_cher")
    assert str(SEMAINES_MIN_HISTORIQUE) in absente["raison"]


# ------------------------------------------------------------- ecart du jour
@sans_base
async def test_l_ecart_du_jour_nomme_ses_deux_bornes(
    base_jeune: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les prix vont de 1,700 par pas de 1 millime : la reponse est connue."""
    corps = await _anecdotes(base_jeune, monkeypatch)
    ecart = corps["ecart_du_jour"]
    assert isinstance(ecart, dict)
    attendu = STATIONS_MIN_FRANCE + 20
    assert ecart["stations"] == attendu
    assert ecart["prix_min_eur_l"] == 1.700
    assert ecart["prix_max_eur_l"] == pytest.approx(1.700 + (attendu - 1) / 1000, abs=1e-9)
    assert ecart["ecart_eur_l"] == pytest.approx((attendu - 1) / 1000, abs=1e-9)
    assert ecart["moins_chere"]["prix_eur_l"] == ecart["prix_min_eur_l"]
    assert ecart["plus_chere"]["prix_eur_l"] == ecart["prix_max_eur_l"]
    assert ecart["moins_chere"]["ville"] == "Marseille"


@sans_base
async def test_sous_le_seuil_l_ecart_du_jour_ne_parle_pas_de_la_france(
    base_sans_rien: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with psycopg.connect(base_sans_rien, autocommit=True) as connexion:
        connexion.execute(_stations_et_prix(STATIONS_MIN_FRANCE - 1).encode())
        connexion.execute("REFRESH MATERIALIZED VIEW marts.reference_departementale")
    corps = await _anecdotes(base_sans_rien, monkeypatch)
    assert corps["ecart_du_jour"] is None
    indisponibles = corps["indisponibles"]
    assert isinstance(indisponibles, list)
    absente = next(i for i in indisponibles if i["cle"] == "ecart_du_jour")
    assert f"{STATIONS_MIN_FRANCE - 1} stations" in absente["mesure"]


# ------------------------------------------------------- departement et autoroute
@sans_base
async def test_le_departement_sous_le_seuil_de_stations_est_ecarte(
    base_jeune: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le `99` est le moins cher du jeu, mais il n'a pas assez de stations.

    Sans ce filtre, le classement des departements serait gagne par celui qui a le
    moins de stations, pas par le moins cher.
    """
    corps = await _anecdotes(base_jeune, monkeypatch)
    departement = corps["departement_moins_cher"]
    assert isinstance(departement, dict)
    assert departement["code_departement"] == "46", "le 99 est sous le seuil"
    assert departement["prix_median_eur_l"] == pytest.approx(1.810)
    assert departement["prix_national_eur_l"] == pytest.approx(1.860)
    assert departement["ecart_au_national_eur_l"] == pytest.approx(-0.050)
    assert departement["departements_compares"] == 2, "le 46 et le 75, pas le 99"
    assert departement["jours"] == 7


@sans_base
async def test_le_surcout_autoroutier_porte_sur_cinquante_litres(
    base_jeune: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    corps = await _anecdotes(base_jeune, monkeypatch)
    autoroute = corps["surcout_autoroute"]
    assert isinstance(autoroute, dict)
    assert autoroute["ecart_eur_l"] == pytest.approx(2.090 - 1.850)
    assert autoroute["litres"] == 50
    assert autoroute["surcout_eur"] == pytest.approx(12.00, abs=0.005)


# -------------------------------------------------- le retrait de tendance
@sans_base
async def test_une_tendance_pure_ne_designe_aucun_jour(
    base_sans_rien: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le test central : sans effet hebdomadaire, les sept ecarts doivent etre nuls.

    Le jeu ne contient qu'une hausse reguliere de 1 millime par jour sur 800 jours.
    Une moyenne brute par jour de la semaine y verrait pourtant un gagnant, parce
    que la serie ne couvre pas un nombre entier de semaines : deux jours ont une
    observation de plus, prise a la fin de la serie, donc plus chere. Le test
    verifie les deux : la moyenne brute se trompe, la methode retenue ne se trompe
    pas.
    """
    with psycopg.connect(base_sans_rien, autocommit=True) as connexion:
        connexion.execute(_agregats_historiques({}).encode())
        brut = connexion.execute(
            "SELECT max(m) - min(m) FROM ("
            "  SELECT avg(prix_median) AS m FROM marts.agregat_prix_jour"
            "   WHERE carburant = 'gazole' AND dimension = 'france'"
            "   GROUP BY extract(isodow FROM jour)) s"
        ).fetchone()
    assert brut is not None
    ecart_brut = float(brut[0])

    corps = await _anecdotes(base_sans_rien, monkeypatch)
    jour = corps["jour_semaine_moins_cher"]
    assert isinstance(jour, dict)
    classement = jour["classement"]
    assert len(classement) == 7
    ecarts = [c["ecart_eur_l"] for c in classement]
    ecart_methode = max(ecarts) - min(ecarts)

    assert ecart_brut > 0.001, (
        "le jeu doit bien piéger une moyenne brute, sinon le test ne prouve rien "
        f"(ecart brut mesure : {ecart_brut})"
    )
    assert ecart_methode < 1e-9, (
        f"une tendance pure ne doit designer aucun jour (ecart obtenu : {ecart_methode})"
    )
    assert ecart_brut / max(ecart_methode, 1e-12) > 1000


@sans_base
async def test_un_effet_hebdomadaire_plante_est_retrouve_exactement(
    base_sans_rien: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un mardi a 1 centime de moins doit sortir, et avec la bonne valeur.

    La moyenne glissante de sept jours contient le mardi lui-meme : elle est donc
    abaissee de 1/7 de l'effet. L'ecart attendu pour le mardi est 6/7 de l'effet,
    et pour les six autres jours +1/7. Exiger ces valeurs plutot que le seul
    classement verifie qu'on a compris la methode, pas seulement qu'elle sort un
    gagnant.
    """
    effet = -0.010
    with psycopg.connect(base_sans_rien, autocommit=True) as connexion:
        connexion.execute(_agregats_historiques({2: effet}).encode())

    corps = await _anecdotes(base_sans_rien, monkeypatch)
    jour = corps["jour_semaine_moins_cher"]
    assert isinstance(jour, dict)
    assert jour["jour_semaine"] == 2, "le mardi"
    assert jour["semaines"] >= SEMAINES_MIN_HISTORIQUE
    assert jour["ecart_eur_l"] == pytest.approx(effet * 6 / 7, abs=1e-5)
    for ligne in jour["classement"]:
        attendu = effet * 6 / 7 if ligne["jour_semaine"] == 2 else -effet / 7
        assert ligne["ecart_eur_l"] == pytest.approx(attendu, abs=1e-5), ligne


# ------------------------------------------------------------------ validation
@sans_base
async def test_un_carburant_inconnu_est_refuse_avec_la_liste(
    base_sans_rien: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", base_sans_rien)
    app = creer_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as cliente,
    ):
        reponse = await cliente.get("/v1/anecdotes/du-jour", params={"carburant": "diesel"})
    assert reponse.status_code == 422
    assert reponse.headers["content-type"].startswith("application/problem+json")
    assert "gazole" in reponse.json()["detail"], "l'erreur doit lister les valeurs acceptees"
