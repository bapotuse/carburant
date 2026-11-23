from __future__ import annotations

import pytest
from carburant_mcp.serveur import API_PAR_DEFAUT, base_api, main


def test_le_point_d_entree_existe_et_repond() -> None:
    assert main(["--transport", "stdio"]) == 0


def test_les_deux_transports_sont_acceptes() -> None:
    assert main(["--transport", "http"]) == 0


def test_un_transport_inconnu_est_refuse() -> None:
    with pytest.raises(SystemExit):
        main(["--transport", "carrier-pigeon"])


def test_l_url_de_l_api_est_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARBURANT_API_BASE", "http://localhost:8000/v1/")
    assert base_api() == "http://localhost:8000/v1"


def test_sans_configuration_le_serveur_pointe_sur_la_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un recruteur qui lance `uvx prix-carburant-mcp` ne configure rien."""
    monkeypatch.delenv("CARBURANT_API_BASE", raising=False)
    assert base_api() == API_PAR_DEFAUT


def test_le_dossier_mcp_ne_masque_pas_le_sdk() -> None:
    """Le layout src/ existe pour ca : `import mcp` doit atteindre le SDK officiel,
    pas le dossier du projet."""
    import mcp

    assert "carburant" not in (mcp.__file__ or "")
