"""Telechargement du flux : reessais, empreinte, deduplication, retention.

La source reelle n'est pas appelee ici -- respx simule le reseau -- sauf dans le test
marque `reseau`, qui lui parle vraiment au flux public.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
from pathlib import Path

import httpx
import pytest
import respx
from carburant_etl.config import URL_FLUX_EXPORT
from carburant_etl.sources import flux_v2
from carburant_etl.sources.flux_v2 import (
    CollecteEchouee,
    nom_de_fichier,
    purger,
    telecharger,
)

AGENT = "carburant-test/0.1"
CORPS = json.dumps([{"id": 56580001, "gazole_prix": 2.109}]).encode()


@pytest.fixture(autouse=True)
def _pas_d_attente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les reessais ne doivent pas rendre la suite de tests lente."""
    monkeypatch.setattr(flux_v2, "_attendre", lambda _secondes: None)


@respx.mock
def test_telechargement_nominal(tmp_path: Path) -> None:
    respx.get(URL_FLUX_EXPORT).mock(return_value=httpx.Response(200, content=CORPS))
    collecte = telecharger(tmp_path, user_agent=AGENT)

    assert collecte.inchange is False
    assert collecte.octets == len(CORPS)
    assert collecte.chemin is not None
    assert collecte.chemin.exists()
    assert collecte.duree_secondes >= 0
    with gzip.open(collecte.chemin, "rb") as flux:
        assert flux.read() == CORPS


@respx.mock
def test_le_user_agent_identifie_le_projet(tmp_path: Path) -> None:
    """Une source publique doit pouvoir savoir qui l'interroge."""
    route = respx.get(URL_FLUX_EXPORT).mock(return_value=httpx.Response(200, content=CORPS))
    telecharger(tmp_path, user_agent="carburant/0.1 (+https://github.com/bapotuse)")
    envoye = route.calls.last.request.headers["user-agent"]
    assert "carburant" in envoye
    assert "github.com" in envoye


@respx.mock
def test_un_contenu_identique_ne_cree_pas_de_second_fichier(tmp_path: Path) -> None:
    """Le flux ne bouge pas a chaque collecte : inutile d'en garder douze copies par heure."""
    respx.get(URL_FLUX_EXPORT).mock(return_value=httpx.Response(200, content=CORPS))

    premiere = telecharger(tmp_path, user_agent=AGENT)
    seconde = telecharger(tmp_path, user_agent=AGENT)

    assert premiere.inchange is False
    assert seconde.inchange is True
    assert seconde.chemin is None
    # La collecte a bien eu lieu : meme empreinte, meme taille.
    assert seconde.sha256 == premiere.sha256
    assert len(list(tmp_path.glob("flux-v2-*.json.gz"))) == 1


@respx.mock
def test_un_contenu_different_cree_bien_un_fichier(tmp_path: Path) -> None:
    respx.get(URL_FLUX_EXPORT).mock(return_value=httpx.Response(200, content=CORPS))
    telecharger(tmp_path, user_agent=AGENT)

    autre = json.dumps([{"id": 56580001, "gazole_prix": 2.119}]).encode()
    respx.get(URL_FLUX_EXPORT).mock(return_value=httpx.Response(200, content=autre))
    seconde = telecharger(tmp_path, user_agent=AGENT)

    assert seconde.inchange is False
    assert len(list(tmp_path.glob("flux-v2-*.json.gz"))) == 2


@respx.mock
def test_reessaie_puis_reussit(tmp_path: Path) -> None:
    respx.get(URL_FLUX_EXPORT).mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectError("coupure"),
            httpx.Response(200, content=CORPS),
        ]
    )
    collecte = telecharger(tmp_path, user_agent=AGENT)
    assert collecte.inchange is False
    assert collecte.octets == len(CORPS)


@respx.mock
def test_abandonne_apres_cinq_tentatives(tmp_path: Path) -> None:
    route = respx.get(URL_FLUX_EXPORT).mock(return_value=httpx.Response(503))
    with pytest.raises(CollecteEchouee, match="5 tentatives"):
        telecharger(tmp_path, user_agent=AGENT)
    assert route.call_count == 5
    assert list(tmp_path.glob("*.json.gz")) == []


@respx.mock
def test_une_source_qui_disparait_echoue_franchement(tmp_path: Path) -> None:
    respx.get(URL_FLUX_EXPORT).mock(return_value=httpx.Response(404))
    with pytest.raises(CollecteEchouee):
        telecharger(tmp_path, user_agent=AGENT)


def test_la_purge_respecte_la_retention(tmp_path: Path) -> None:
    reference = dt.datetime(2026, 11, 23, 12, 0, tzinfo=dt.UTC)
    for jours in (0, 5, 13, 14, 15, 40):
        horodatage = reference - dt.timedelta(days=jours)
        (tmp_path / nom_de_fichier(horodatage, "abcdef0123456789")).write_bytes(b"x")

    supprimes = purger(tmp_path, retention_jours=14, reference=reference)

    assert supprimes == 2  # les fichiers de 15 et 40 jours
    assert len(list(tmp_path.glob("flux-v2-*.json.gz"))) == 4


def test_la_purge_ignore_un_repertoire_absent(tmp_path: Path) -> None:
    assert purger(tmp_path / "jamais-cree", retention_jours=14) == 0


@pytest.mark.reseau
def test_contre_la_vraie_source(tmp_path: Path) -> None:
    """Appelle vraiment data.economie.gouv.fr.

    Marque `reseau` : exclu de `make check`, lance explicitement par
    `uv run pytest -m reseau`. Il verifie ce qu'aucune simulation ne peut verifier --
    que le contrat de la source n'a pas change.
    """
    collecte = telecharger(tmp_path, user_agent="carburant-test/0.1")

    assert collecte.octets > 1_000_000, "l'export complet fait plusieurs megaoctets"
    assert collecte.chemin is not None
    with gzip.open(collecte.chemin, "rb") as flux:
        lignes = json.load(flux)

    assert len(lignes) > 8_000, f"seulement {len(lignes)} stations"
    premiere = lignes[0]
    for champ in ("id", "cp", "adresse", "ville", "geom", "pop", "code_departement"):
        assert champ in premiere, f"champ {champ} disparu du flux"
    assert isinstance(premiere["geom"], dict)
    assert {"lat", "lon"} <= set(premiere["geom"])


def test_deux_collectes_dans_la_meme_seconde_ne_s_ecrasent_pas() -> None:
    """Le nom porte l'empreinte, pas seulement l'horodatage a la seconde."""
    instant = dt.datetime(2026, 11, 23, 17, 46, 50, tzinfo=dt.UTC)
    a = nom_de_fichier(instant, "aaaaaaaaaaaabbbb")
    b = nom_de_fichier(instant, "ccccccccccccdddd")
    assert a != b
    assert a.startswith("flux-v2-20261123T174650Z-")


def test_la_purge_laisse_tranquille_un_fichier_au_nom_inattendu(tmp_path: Path) -> None:
    """On ne supprime jamais a l'aveugle un fichier qu'on ne sait pas dater."""
    etrange = tmp_path / "flux-v2-pas-une-date.json.gz"
    etrange.write_bytes(b"x")
    assert purger(tmp_path, retention_jours=0) == 0
    assert etrange.exists()
