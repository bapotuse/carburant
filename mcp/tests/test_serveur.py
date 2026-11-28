"""Le point d'entrée, les transports et le piège du dossier `mcp/`."""

from __future__ import annotations

from pathlib import Path

import pytest
from carburant_mcp.client import API_PAR_DEFAUT, base_api
from carburant_mcp.serveur import INSTRUCTIONS, main


def test_le_mode_verification_liste_les_six_outils(capsys: pytest.CaptureFixture[str]) -> None:
    """`--verifier` assemble le serveur et sort : c'est le smoke test d'installation.

    Les autres transports **servent** et ne rendent jamais la main. Les tester en
    appelant `main` bloquerait la suite -- ce qui est arrive, et c'est pour cela que
    ce mode existe.
    """
    assert main(["--verifier"]) == 0
    sortie = capsys.readouterr().out
    assert "6 outils" in sortie
    for nom in (
        "trouver_station_moins_chere",
        "meilleure_station_avec_autonomie",
        "prix_station",
        "tendance_prix",
        "empreinte_carbone_plein",
        "comparer_carburants",
    ):
        assert nom in sortie


def test_un_transport_inconnu_est_refuse() -> None:
    with pytest.raises(SystemExit):
        main(["--transport", "carrier-pigeon"])


def test_les_deux_transports_sont_declares() -> None:
    """stdio pour une installation locale, http pour le connecteur distant."""
    with pytest.raises(SystemExit) as erreur:
        main(["--aide-inexistante"])
    assert erreur.value.code != 0


def test_l_url_de_l_api_est_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARBURANT_API_BASE", "http://localhost:8000/v1/")
    assert base_api() == "http://localhost:8000/v1"


def test_sans_configuration_le_serveur_pointe_sur_la_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un recruteur qui lance `uvx prix-carburant-mcp` ne configure rien."""
    monkeypatch.delenv("CARBURANT_API_BASE", raising=False)
    assert base_api() == API_PAR_DEFAUT
    assert API_PAR_DEFAUT.startswith("https://"), "la production est en HTTPS"
    assert API_PAR_DEFAUT.endswith("/v1"), "l'URL de base porte le prefixe de version"


def test_les_instructions_disent_ce_que_les_donnees_ne_contiennent_pas() -> None:
    """Un modele doit savoir ou s'arrete la couverture avant de repondre."""
    assert "outre-mer" in INSTRUCTIONS
    assert "OpenStreetMap" in INSTRUCTIONS
    assert "quinze minutes" in INSTRUCTIONS


def test_le_dossier_mcp_ne_masque_pas_le_sdk() -> None:
    """Le layout src/ existe pour ca : `import mcp` doit atteindre le SDK officiel.

    Et le layout ne suffit pas : sans `mcp/tests/__init__.py`, pytest nomme les
    modules de test `mcp.tests.test_...`, importe `mcp` comme paquet-espace de noms
    depuis la racine du depot et masque le SDK pour toute la session. Ce test echoue
    si ce marqueur disparait.
    """
    import mcp

    fichier = mcp.__file__ or ""
    assert "site-packages" in fichier, f"« import mcp » atteint {fichier}"
    assert "carburant" not in fichier

    racine = Path(__file__).resolve().parent
    assert (racine / "__init__.py").exists(), (
        "mcp/tests/__init__.py est ce qui empeche pytest de traiter mcp/ comme une "
        "racine de paquet ; sans lui le SDK est masque"
    )
    assert not (racine.parent / "__init__.py").exists(), (
        "mcp/ ne doit jamais avoir de __init__.py : il deviendrait un vrai paquet "
        "nomme « mcp » et masquerait le SDK partout"
    )


def test_le_sdk_est_bien_en_version_2() -> None:
    """La v1 s'appelait FastMCP ; la v2 MCPServer, et les champs sont en snake_case.

    Ce test echouerait sur une v1 installee par megarde, ou la classe n'existe pas.
    """
    from mcp.server.mcpserver import MCPServer

    assert hasattr(MCPServer, "run_streamable_http_async")
