from __future__ import annotations

from carburant_api.app import creer_app, origines_autorisees
from carburant_api.version import PREFIXE, VERSION
from fastapi.testclient import TestClient


def test_l_openapi_est_servie_sous_le_prefixe_de_version() -> None:
    client = TestClient(creer_app())
    schema = client.get(f"{PREFIXE}/openapi.json").json()
    assert schema["info"]["version"] == VERSION
    assert f"{PREFIXE}/sante" in schema["paths"]


def test_chaque_route_a_un_resume_et_une_description() -> None:
    """L'OpenAPI est consommee par le front et par le MCP : elle doit etre lisible."""
    schema = TestClient(creer_app()).get(f"{PREFIXE}/openapi.json").json()
    for chemin, operations in schema["paths"].items():
        for methode, operation in operations.items():
            assert operation.get("summary"), f"{methode.upper()} {chemin} sans resume"
            assert operation.get("description"), f"{methode.upper()} {chemin} sans description"


def test_cors_ne_vaut_jamais_etoile() -> None:
    assert "*" not in origines_autorisees()
