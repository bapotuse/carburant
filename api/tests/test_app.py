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


def test_l_openapi_declare_le_429_partout_sauf_sur_les_exemptions() -> None:
    """Le middleware est invisible pour FastAPI : on declare son effet a la main.

    Un client genere depuis cet OpenAPI -- le front, le serveur MCP -- n'aurait
    autrement aucune raison de prevoir un refus pour exces de debit. Et la liste des
    exemptions est **lue** dans le middleware plutot que recopiee, pour que le
    comportement et sa documentation ne puissent pas diverger : ce test compare les
    deux.
    """
    from carburant_api.app import creer_app
    from carburant_api.limite import MiddlewareLimite

    schema = creer_app().openapi()
    chemins = schema["paths"]
    assert chemins, "l'OpenAPI doit decrire des chemins"

    for chemin, operations in chemins.items():
        for methode, operation in operations.items():
            codes = set(operation["responses"])
            if chemin in MiddlewareLimite.EXEMPTS:
                assert "429" not in codes, (
                    f"{methode.upper()} {chemin} est exempte de la limitation : "
                    "annoncer un 429 serait faux"
                )
            else:
                assert "429" in codes, f"{methode.upper()} {chemin} n'annonce pas le 429"


def test_l_openapi_est_mis_en_cache() -> None:
    """Deux appels doivent rendre le meme objet, 429 injecte une seule fois.

    L'injection remplace `app.openapi` : si elle oubliait le cache de FastAPI, le
    schema serait reconstruit a chaque appel de `/v1/openapi.json`.
    """
    from carburant_api.app import creer_app

    app = creer_app()
    assert app.openapi() is app.openapi()
