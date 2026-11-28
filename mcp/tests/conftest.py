"""Session MCP en mémoire, branchée sur une API simulée.

**Pourquoi en mémoire plutôt qu'en lançant un processus** : les tests passent alors
par le vrai protocole — initialisation, `list_tools`, `call_tool`, schémas d'entrée et
de sortie — sans payer un processus ni un port. C'est le seul moyen de vérifier ce
qu'un client voit réellement, et pas seulement ce que nos fonctions renvoient.

Le SDK 2.x ne publie pas de transport en mémoire tout fait : il fournit la paire de
flux (`create_client_server_memory_streams`) et laisse l'appelant brancher les deux
bouts. On passe donc par le serveur bas niveau, seul objet qui accepte des flux.
C'est une entrée privée du SDK, assumée ici parce qu'il n'y a pas d'équivalent public
et que ces tests sont les seuls à en dépendre.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
from carburant_mcp.client import ClientCarburant
from carburant_mcp.serveur import creer_serveur
from mcp.shared.memory import create_client_server_memory_streams

from mcp import ClientSession

BASE = "https://api.test/v1"
REPONSES = Path(__file__).parent / "reponses"


def charger(nom: str) -> dict[str, Any]:
    """Une réponse réelle de l'API, capturée le 28/11/2026 contre la vraie base.

    Des réponses capturées plutôt qu'inventées : une forme devinée se met d'accord
    avec le code qui la consomme et ne prouve rien. Celles-ci viennent de l'API qui
    tourne, avec ses vrais prix et ses vraies stations marseillaises.
    """
    charge: dict[str, Any] = json.loads((REPONSES / f"{nom}.json").read_text(encoding="utf-8"))
    return charge


# Réponses dont la capture a échoué dans l'environnement de développement : le
# conteneur de l'API n'y joint ni l'IGN ni l'ADEME. Les chiffres ne sont pas inventés
# pour autant — les scores de géocodage sont ceux mesurés dans
# `docs/reconnaissance.md` section 3, et les facteurs d'émission ceux de la Base
# Carbone relevés le 23/11/2026 (section 4).
GEOCODE_PRECIS: dict[str, Any] = {
    "requete": "40 avenue du Prado, 13006 Marseille",
    "ambigu": False,
    "raison": None,
    "candidats": [
        {
            "libelle": "40 Avenue du Prado 13006 Marseille",
            "ville": "Marseille",
            "code_postal": "13006",
            "latitude": 43.2843,
            "longitude": 5.3823,
            "score": 0.972,
            "type": "housenumber",
        },
        {
            "libelle": "Avenue du Prado 13008 Marseille",
            "ville": "Marseille",
            "code_postal": "13008",
            "latitude": 43.2726,
            "longitude": 5.3846,
            "score": 0.455,
            "type": "street",
        },
    ],
}

GEOCODE_AMBIGU: dict[str, Any] = {
    "requete": "le Prado, Marseille",
    "ambigu": True,
    "raison": "le meilleur candidat ne marque que 0,608",
    "candidats": [
        {
            "libelle": "Avenue du Prado 13006 Marseille",
            "ville": "Marseille",
            "code_postal": "13006",
            "latitude": 43.2843,
            "longitude": 5.3823,
            "score": 0.608,
            "type": "street",
        },
        {
            "libelle": "Avenue du Prado 13008 Marseille",
            "ville": "Marseille",
            "code_postal": "13008",
            "latitude": 43.2726,
            "longitude": 5.3846,
            "score": 0.605,
            "type": "street",
        },
    ],
}

EMPREINTE_GAZOLE: dict[str, Any] = {
    "carburant": "gazole",
    "litres": 40.0,
    "co2_kg": 124.0,
    "facteur": {
        "carburant": "gazole",
        "valeur_kg_co2e_par_litre": 3.1,
        "unite": "kgCO2e/litre",
        "libelle_ademe": "Gazole routier / B7",
        "localisation": "France continentale",
        "statut": "Valide générique",
        "periode_validite": "déc-20",
        "version_base": "2026-06-30T10:17:08.470Z",
        "url": "https://data.ademe.fr/datasets/base-carbone(r)",
    },
}

COMPARAISON: dict[str, Any] = {
    "litres": 40.0,
    "empreintes": [
        {"carburant": "gazole", "facteur_kg_co2e_par_litre": 3.1, "co2_kg": 124.0},
        {"carburant": "sp95", "facteur_kg_co2e_par_litre": 2.69, "co2_kg": 107.6},
        {"carburant": "e10", "facteur_kg_co2e_par_litre": 2.69, "co2_kg": 107.6},
        {"carburant": "sp98", "facteur_kg_co2e_par_litre": 2.69, "co2_kg": 107.6},
        {"carburant": "e85", "facteur_kg_co2e_par_litre": 1.11, "co2_kg": 44.4},
        {"carburant": "gplc", "facteur_kg_co2e_par_litre": 1.86, "co2_kg": 74.4},
    ],
    "avertissement": (
        "Un litre d'E85 ne fait pas la meme distance qu'un litre de gazole : comparer "
        "les prix au litre ne compare pas les couts d'usage. Le facteur de l'E85 "
        "n'inclut pas le carbone de la biomasse, par convention de la Base Carbone."
    ),
    "source": "ADEME, Base Carbone, jeu du 2026-06-30T10:17:08.470Z",
}


# Les bornes que l'API impose a ses parametres, recopiees de l'OpenAPI. Le faux
# client les fait respecter : sans cela, un outil peut demander `limite=200`, passer
# tous les tests, puis echouer en production avec « Input should be less than or
# equal to 100 ». C'est exactement ce qui est arrive a `comparer_carburants`, et
# c'est l'essai de bout en bout qui l'a vu -- ces tests ne pouvaient pas.
BORNES: dict[str, tuple[float, float]] = {
    "limite": (1, 100),
    "rayon_km": (0.1, 50),
    "jours": (1, 1825),
    "litres": (0.1, 500),
    "autonomie_km": (0.1, 1500),
}


def _verifier_les_bornes(requete: httpx.Request) -> None:
    """Refuse comme l'API refuserait : hors bornes, c'est un 422."""
    for nom, (bas, haut) in BORNES.items():
        brut = requete.url.params.get(nom)
        if brut is None:
            continue
        valeur = float(brut)
        if not bas <= valeur <= haut:
            raise AssertionError(
                f"{requete.url.path} demande {nom}={brut}, hors des bornes "
                f"[{bas}, {haut}] de l'API. En production, elle aurait repondu 422."
            )


@pytest.fixture
def api() -> Callable[[dict[str, dict[str, Any]]], httpx.AsyncClient]:
    """Fabrique un client httpx qui répond depuis une table chemin → charge.

    Un `MockTransport` plutôt que des routes respx : la table se lit d'un coup d'œil,
    et une requête vers un chemin non prévu **échoue** au lieu de rendre un 404
    silencieux. Un test qui appelle une route qu'il n'a pas déclarée est un test qui
    ne sait pas ce qu'il teste.
    """

    def fabriquer(table: dict[str, dict[str, Any]]) -> httpx.AsyncClient:
        appels: list[str] = []

        def repondre(requete: httpx.Request) -> httpx.Response:
            chemin = requete.url.path
            appels.append(chemin)
            _verifier_les_bornes(requete)
            if chemin in table:
                return httpx.Response(200, json=table[chemin])
            raise AssertionError(
                f"chemin non prevu par le test : {chemin}\n"
                f"prevus : {sorted(table)}\nappeles : {appels}"
            )

        return httpx.AsyncClient(
            transport=httpx.MockTransport(repondre), base_url=BASE, timeout=5.0
        )

    return fabriquer


@pytest.fixture
def charges() -> dict[str, dict[str, Any]]:
    """Toutes les charges d'essai, par nom.

    Exposees en fixture et non importees depuis ce fichier : un test qui ferait
    `from conftest import ...` obligerait `mcp/tests` a etre importable sous ce nom,
    ce qui depend du mode d'import de pytest. Les fixtures, elles, marchent toujours.
    """
    return {
        "proches": charger("proches_gazole_prado"),
        "meilleure": charger("meilleure_gazole_prado"),
        "tendances": charger("tendances_gazole_30j"),
        "geocode_precis": GEOCODE_PRECIS,
        "geocode_ambigu": GEOCODE_AMBIGU,
        "empreinte_gazole": EMPREINTE_GAZOLE,
        "comparaison": COMPARAISON,
    }


@pytest.fixture
def ouvrir() -> Callable[[httpx.AsyncClient], AbstractAsyncContextManager[ClientSession]]:
    """Ouvre une session MCP en memoire sur un client HTTP donne.

    Nommee `ouvrir` et non `session` : les tests ecrivent
    `async with ouvrir(client) as cliente`, et deux noms distincts valent mieux qu'un
    seul qui masquerait la fabrique par la session ouverte.
    """
    return _session_mcp


@asynccontextmanager
async def _session_mcp(client_http: httpx.AsyncClient) -> AsyncIterator[ClientSession]:
    """Une session client MCP connectée au vrai serveur, en mémoire."""
    async with ClientCarburant(base=BASE, client=client_http) as client:
        serveur = creer_serveur(client)
        bas = serveur._lowlevel_server
        options = bas.create_initialization_options()
        async with (
            create_client_server_memory_streams() as (cote_client, cote_serveur),
            anyio.create_task_group() as groupe,
        ):

            async def servir() -> None:
                await bas.run(cote_serveur[0], cote_serveur[1], options, raise_exceptions=True)

            groupe.start_soon(servir)
            async with ClientSession(cote_client[0], cote_client[1]) as session:
                await session.initialize()
                yield session
            groupe.cancel_scope.cancel()
