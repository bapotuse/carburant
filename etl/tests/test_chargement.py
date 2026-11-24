"""Chargement en staging et migrations, contre une vraie base PostGIS.

Marques `integration` : ils ont besoin d'une base joignable via `DATABASE_URL`. La CI
en fournit une (service `postgis/postgis`), et `make check` les ecarte pour pouvoir
tourner hors ligne.

Chaque test travaille dans sa propre base jetable : les tests ne se marchent pas
dessus et ne laissent rien derriere eux.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from carburant_etl.chargement.migrations import MigrationModifiee, appliquer, lister
from carburant_etl.chargement.staging import (
    charger,
    marquer_echec,
    ouvrir,
    purger_staging,
)
from carburant_etl.modeles import Aplatissement, LignePrix, LigneStation, Rejets
from carburant_etl.sources.flux_v2 import Collecte

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")


@pytest.fixture
def base() -> Iterator[str]:
    """Cree une base jetable, applique les migrations, la supprime a la fin."""
    assert URL
    nom = f"carburant_test_{uuid.uuid4().hex[:12]}"
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


def collecte(sha: str = "a" * 64, octets: int = 1234) -> Collecte:
    instant = dt.datetime(2026, 11, 24, 18, 0, tzinfo=dt.UTC)
    return Collecte(
        source="flux-v2",
        url="https://exemple/exports/json",
        debut=instant,
        fin=instant + dt.timedelta(seconds=3),
        octets=octets,
        sha256=sha,
        chemin=Path("/brut/flux.json.gz"),
        inchange=False,
    )


def aplatissement() -> Aplatissement:
    rejets = Rejets()
    rejets.noter("e85_prix", "hors bornes absolues", 1.99)
    rejets.noter("e85_prix", "hors bornes absolues", 1.99)
    return Aplatissement(
        stations=[
            LigneStation(
                station_id=56580001,
                longitude=-2.69,
                latitude=48.061,
                cp="56580",
                adresse="16 rue chateaubriand",
                ville="Brehan",
                pop="R",
                departement="Morbihan",
                code_departement="56",
                region="Bretagne",
                code_region="53",
                horaires={"automate_24_24": True, "jours": []},
                services=["Piste poids lourds", "Automate CB 24/24"],
            )
        ],
        prix=[
            LignePrix(
                station_id=56580001,
                carburant="gazole",
                prix=2.109,
                maj="2026-11-23T16:00:00+00:00",
                rupture_type=None,
                rupture_debut=None,
            ),
            LignePrix(
                station_id=56580001,
                carburant="gplc",
                prix=None,
                maj=None,
                rupture_type="definitive",
                rupture_debut="2017-10-06T14:05:31+00:00",
            ),
        ],
        rejets=rejets,
        lignes_lues=1,
    )


# ---------------------------------------------------------------- migrations


@sans_base
def test_les_migrations_creent_le_schema_attendu(base: str) -> None:
    with psycopg.connect(base) as connexion:
        curseur = connexion.execute(
            "SELECT string_agg(nspname, ',' ORDER BY nspname) FROM pg_namespace "
            "WHERE nspname IN ('raw', 'staging', 'marts', 'meta')"
        )
        ligne = curseur.fetchone()
    assert ligne is not None
    assert ligne[0] == "marts,meta,raw,staging"


@sans_base
def test_postgis_est_disponible(base: str) -> None:
    with psycopg.connect(base) as connexion:
        curseur = connexion.execute("SELECT postgis_version()")
        ligne = curseur.fetchone()
    assert ligne is not None and ligne[0]


@sans_base
def test_les_migrations_sont_idempotentes(base: str) -> None:
    assert appliquer(base) == [], "une seconde application ne doit rien faire"


@sans_base
def test_une_migration_modifiee_apres_coup_est_refusee(base: str, tmp_path: Path) -> None:
    """Deux bases qui divergent en silence coutent bien plus cher qu'un echec franc."""
    for migration in lister():
        copie = tmp_path / migration.nom
        copie.write_text(migration.chemin.read_text(encoding="utf-8"), encoding="utf-8")
    premiere = sorted(tmp_path.glob("*.sql"))[0]
    premiere.write_text(
        premiere.read_text(encoding="utf-8") + "\n-- modification apres coup\n",
        encoding="utf-8",
    )
    with pytest.raises(MigrationModifiee, match="contenu a change"):
        appliquer(base, tmp_path)


# ---------------------------------------------------------------- chargement


@sans_base
def test_chargement_complet(base: str) -> None:
    with ouvrir(base) as connexion:
        collecte_id = charger(connexion, collecte(), aplatissement())

        curseur = connexion.execute(
            "SELECT statut, lignes, octets, sha256 FROM raw.collecte WHERE id = %s",
            (collecte_id,),
        )
        trace = curseur.fetchone()
        assert trace == ("succes", 2, 1234, "a" * 64)

        curseur = connexion.execute(
            "SELECT ville, pop, code_departement, horaires, services "
            "FROM staging.station WHERE collecte_id = %s",
            (collecte_id,),
        )
        station = curseur.fetchone()
        assert station is not None
        assert station[0] == "Brehan"
        assert station[1] == "R"
        assert station[2] == "56"
        # Le jsonb est bien du jsonb, pas une chaine.
        assert station[3] == {"automate_24_24": True, "jours": []}
        # Le text[] est bien un tableau.
        assert station[4] == ["Piste poids lourds", "Automate CB 24/24"]


@sans_base
def test_les_horodatages_sont_stockes_en_utc(base: str) -> None:
    """Le prix a ete mis a jour a 17 h 00 a Paris, soit 16 h 00 UTC."""
    with ouvrir(base) as connexion:
        charger(connexion, collecte(), aplatissement())
        curseur = connexion.execute("SELECT maj FROM staging.prix WHERE carburant = 'gazole'")
        ligne = curseur.fetchone()
    assert ligne is not None
    # psycopg rend un datetime conscient de son fuseau : on le compare tel quel,
    # plutot que de le denuder avec `AT TIME ZONE` et de comparer du naif.
    assert ligne[0] == dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.UTC)


@sans_base
def test_une_rupture_sans_prix_est_chargee(base: str) -> None:
    with ouvrir(base) as connexion:
        charger(connexion, collecte(), aplatissement())
        curseur = connexion.execute(
            "SELECT prix, rupture_type FROM staging.prix WHERE carburant = 'gplc'"
        )
        ligne = curseur.fetchone()
    assert ligne == (None, "definitive")


@sans_base
def test_les_rejets_sont_charges_avec_leur_compte_et_un_exemple(base: str) -> None:
    with ouvrir(base) as connexion:
        collecte_id = charger(connexion, collecte(), aplatissement())
        curseur = connexion.execute(
            "SELECT champ, motif, occurrences, exemple FROM staging.rejet WHERE collecte_id = %s",
            (collecte_id,),
        )
        lignes = curseur.fetchall()
    assert lignes == [("e85_prix", "hors bornes absolues", 2, "1.99")]


@sans_base
def test_un_chargement_qui_casse_ne_laisse_rien_derriere(base: str) -> None:
    """Tout ou rien : pas de staging a moitie rempli a nettoyer a la main."""
    casse = Aplatissement(
        stations=aplatissement().stations,
        prix=[
            LignePrix(
                station_id=56580001,
                carburant="kerosene",  # viole la contrainte CHECK
                prix=1.5,
                maj="2026-11-23T16:00:00+00:00",
                rupture_type=None,
                rupture_debut=None,
            )
        ],
        rejets=Rejets(),
        lignes_lues=1,
    )
    with ouvrir(base) as connexion:
        with pytest.raises(psycopg.errors.CheckViolation):
            charger(connexion, collecte(), casse)
        connexion.rollback()
        curseur = connexion.execute("SELECT count(*) FROM raw.collecte")
        ligne = curseur.fetchone()
    assert ligne == (0,), "la collecte ne doit pas exister si le chargement a casse"


@sans_base
def test_une_collecte_peut_etre_marquee_en_echec(base: str) -> None:
    from carburant_etl.chargement.staging import enregistrer_collecte

    with ouvrir(base) as connexion:
        with connexion.transaction():
            collecte_id = enregistrer_collecte(connexion, collecte())
        marquer_echec(connexion, collecte_id, "CollecteEchouee: source injoignable")
        curseur = connexion.execute(
            "SELECT statut, erreur FROM raw.collecte WHERE id = %s", (collecte_id,)
        )
        ligne = curseur.fetchone()
    assert ligne is not None
    assert ligne[0] == "echec"
    assert isinstance(ligne[1], str)
    assert "injoignable" in ligne[1]


@sans_base
def test_la_purge_ne_garde_que_les_dernieres_collectes(base: str) -> None:
    """55 000 lignes toutes les 15 minutes feraient 5,3 millions de lignes par jour."""
    with ouvrir(base) as connexion:
        for i in range(6):
            charger(connexion, collecte(sha=str(i) * 64), aplatissement())

        supprimees = purger_staging(connexion, collectes_a_garder=2)
        curseur = connexion.execute("SELECT count(*) FROM raw.collecte")
        collectes = curseur.fetchone()
        curseur = connexion.execute("SELECT count(*) FROM staging.prix")
        prix = curseur.fetchone()

    assert supprimees == 4
    assert collectes == (2,)
    # Le ON DELETE CASCADE a bien emporte les lignes de staging.
    assert prix == (4,), "2 collectes x 2 lignes de prix"


@sans_base
def test_une_lecture_n_empeche_pas_la_cloture_d_execution(base: str) -> None:
    """Regression : une transaction implicite avalait la cloture de l'execution.

    En mode non-autocommit, psycopg ouvre une transaction des le premier ordre, y
    compris un `SELECT`. Les `with connexion.transaction()` suivants ne sont alors que
    des points de reprise imbriques : ils ne valident rien, et `close()` annule tout.

    Le defaut etait silencieux et grave : un controle qualite en lecture, place entre
    le chargement et la cloture, laissait `meta.execution_etl` bloque sur `en_cours`.
    `/v1/sante` et `/v1/meta` annoncaient donc qu'aucune collecte n'avait jamais
    reussi, alors que les donnees etaient bien chargees.
    """
    from carburant_etl.pipeline import cloturer_execution, demarrer_execution

    with ouvrir(base) as connexion:
        execution_id = demarrer_execution(connexion, "test")
        # La lecture qui declenchait le defaut.
        connexion.execute("SELECT count(*) FROM marts.fact_prix").fetchone()
        cloturer_execution(connexion, execution_id, statut="succes", lignes_par_etape={"load": 1})

    # Nouvelle connexion : on lit ce qui a reellement ete valide.
    with ouvrir(base) as verification:
        curseur = verification.execute(
            "SELECT statut, fin IS NOT NULL, lignes_par_etape "
            "FROM meta.execution_etl WHERE id = %s",
            (execution_id,),
        )
        ligne = curseur.fetchone()

    assert ligne is not None
    assert ligne[0] == "succes", "l'execution doit etre cloturee, pas restee en cours"
    assert ligne[1] is True, "la date de fin doit etre enregistree"
    assert ligne[2] == {"load": 1}
