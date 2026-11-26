"""Verrou d'exclusion entre executions de l'ETL.

Le cas reel qui a motive ce verrou : l'amorcage de l'historique dure une heure, et
supercronic lance une collecte toutes les quinze minutes. Quatre collectes se sont
superposees a un amorcage en cours le 26/11/2026. Rien n'a casse, mais c'etait de la
chance : deux `CREATE TABLE … PARTITION OF` concurrents sur la meme table parente se
bloquent, et `REFRESH MATERIALIZED VIEW CONCURRENTLY` refuse de tourner deux fois.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from carburant_etl.chargement.migrations import appliquer
from carburant_etl.chargement.staging import ouvrir
from carburant_etl.chargement.verrou import DejaEnCours, exclusif

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL")
sans_base = pytest.mark.skipif(not URL, reason="DATABASE_URL absente")


@pytest.fixture
def base() -> Iterator[str]:
    assert URL
    nom = f"carburant_verrou_{uuid.uuid4().hex[:12]}"
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


@sans_base
def test_une_seconde_execution_renonce(base: str) -> None:
    """Elle renonce, elle n'attend pas : une collecte ne doit pas patienter une heure."""
    premiere = ouvrir(base)
    seconde = ouvrir(base)
    try:
        # L'ordre compte : la premiere connexion prend le verrou, puis la seconde
        # essaie et doit lever avant d'atteindre le corps du bloc.
        with (
            exclusif(premiere, operation="amorcage"),
            pytest.raises(DejaEnCours, match="une autre execution"),
            exclusif(seconde, operation="collecte"),
        ):
            pytest.fail("la seconde execution n aurait pas du obtenir le verrou")
    finally:
        premiere.close()
        seconde.close()


@sans_base
def test_le_verrou_est_rendu_a_la_sortie_du_bloc(base: str) -> None:
    premiere = ouvrir(base)
    seconde = ouvrir(base)
    try:
        with exclusif(premiere, operation="amorcage"):
            pass
        # Le bloc est fini : la seconde doit passer.
        with exclusif(seconde, operation="collecte"):
            pass
    finally:
        premiere.close()
        seconde.close()


@sans_base
def test_le_verrou_est_rendu_meme_sur_erreur(base: str) -> None:
    """Une execution qui echoue ne doit pas bloquer toutes les suivantes."""
    premiere = ouvrir(base)
    seconde = ouvrir(base)
    try:
        with pytest.raises(ZeroDivisionError), exclusif(premiere, operation="amorcage"):
            _ = 1 / 0
        with exclusif(seconde, operation="collecte"):
            pass
    finally:
        premiere.close()
        seconde.close()


@sans_base
def test_le_verrou_tombe_avec_la_connexion(base: str) -> None:
    """Un conteneur tue par le noyau ne doit pas laisser un verrou orphelin.

    C'est la raison de choisir un verrou consultatif plutot qu'un fichier ou une
    ligne en base : PostgreSQL le libere quand la session se ferme, quelle qu'en
    soit la raison.
    """
    morte = ouvrir(base)
    with morte.cursor() as curseur:
        curseur.execute("SELECT pg_try_advisory_lock(%s)", (0x43415242,))
    morte.close()

    vivante = ouvrir(base)
    try:
        with exclusif(vivante, operation="collecte"):
            pass
    finally:
        vivante.close()


@sans_base
def test_la_meme_session_peut_reprendre_le_verrou(base: str) -> None:
    """Les verrous consultatifs se reentrent : le pipeline en depend.

    `etl run` prend le verrou, puis appelle le rafraichissement des agregats, qui
    pourrait le reprendre. Dans une meme session, PostgreSQL compte les prises et ne
    bloque pas.
    """
    connexion = ouvrir(base)
    try:
        with exclusif(connexion, operation="collecte"), exclusif(connexion, operation="agregats"):
            pass
        # Et apres les deux sorties, une autre session doit pouvoir passer.
        autre = ouvrir(base)
        try:
            with exclusif(autre, operation="collecte"):
                pass
        finally:
            autre.close()
    finally:
        connexion.close()
