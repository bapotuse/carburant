"""La sante du service ne doit jamais mentir : c'est ce que ces tests verrouillent."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from carburant_api.app import creer_app
from carburant_api.requetes.connexion import EtatBase
from carburant_api.version import PREFIXE
from fastapi.testclient import TestClient


class PoolSimule:
    """Remplace le pool de connexions : les tests de sante ne veulent pas de base."""

    def __init__(self, etat: EtatBase) -> None:
        self.etat = etat

    async def open(self, wait: bool = False) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Construit l'application avec un pool simule et un etat de base pilotable."""

    def fabrique(etat: EtatBase) -> TestClient:
        async def lire_etat_simule(_pool: object) -> EtatBase:
            return etat

        monkeypatch.setattr("carburant_api.routes.sante.lire_etat", lire_etat_simule)
        monkeypatch.setattr("carburant_api.app.creer_pool", lambda: PoolSimule(etat))
        return TestClient(creer_app())

    return fabrique


def test_base_joignable_sans_collecte_encore_faite(client: Any) -> None:
    """Au Jalon 0, aucune collecte n'a eu lieu : une base qui repond suffit."""
    with client(EtatBase(joignable=True, schema_pret=True, derniere_collecte_reussie=None)) as c:
        reponse = c.get(f"{PREFIXE}/sante")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["statut"] == "ok"
    assert corps["base_joignable"] is True
    assert corps["age_derniere_collecte_minutes"] is None


def test_base_injoignable_renvoie_503_et_le_dit(client: Any) -> None:
    """C'est le coeur du sujet : le processus web peut aller bien et le service non."""
    with client(EtatBase(joignable=False, schema_pret=False, derniere_collecte_reussie=None)) as c:
        reponse = c.get(f"{PREFIXE}/sante")
    assert reponse.status_code == 503
    corps = reponse.json()
    assert corps["statut"] == "degrade"
    assert corps["base_joignable"] is False


def test_collecte_recente_est_consideree_saine(client: Any) -> None:
    recente = dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=7)
    with client(EtatBase(joignable=True, schema_pret=True, derniere_collecte_reussie=recente)) as c:
        reponse = c.get(f"{PREFIXE}/sante")
    assert reponse.status_code == 200
    assert reponse.json()["age_derniere_collecte_minutes"] == 7


def test_collecte_trop_vieille_fait_basculer_en_degrade(client: Any) -> None:
    vieille = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=5)
    with client(EtatBase(joignable=True, schema_pret=True, derniere_collecte_reussie=vieille)) as c:
        reponse = c.get(f"{PREFIXE}/sante")
    assert reponse.status_code == 503
    corps = reponse.json()
    assert corps["statut"] == "degrade"
    assert corps["base_joignable"] is True
    assert corps["age_derniere_collecte_minutes"] == 300


def test_la_sante_n_est_jamais_mise_en_cache(client: Any) -> None:
    with client(EtatBase(joignable=True, schema_pret=True, derniere_collecte_reussie=None)) as c:
        reponse = c.get(f"{PREFIXE}/sante")
    assert reponse.headers["cache-control"] == "no-store"


def test_le_seuil_est_configurable(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_SANTE_AGE_MAX_MINUTES", "600")
    vieille = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=5)
    with client(EtatBase(joignable=True, schema_pret=True, derniere_collecte_reussie=vieille)) as c:
        reponse = c.get(f"{PREFIXE}/sante")
    assert reponse.status_code == 200
    assert reponse.json()["age_max_minutes"] == 600


def test_base_joignable_mais_migrations_non_passees(client: Any) -> None:
    """Le cas constate sur une machine propre : le conteneur demarre avant `make migrate`.

    La reponse doit le dire precisement, parce que la reparation n'est pas la meme
    qu'une base injoignable : c'est `make migrate`, pas un redemarrage.
    """
    with client(EtatBase(joignable=True, schema_pret=False, derniere_collecte_reussie=None)) as c:
        reponse = c.get(f"{PREFIXE}/sante")
    assert reponse.status_code == 503
    corps = reponse.json()
    assert corps["statut"] == "degrade"
    assert corps["base_joignable"] is True
    assert corps["schema_pret"] is False
