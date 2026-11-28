"""Construction de l'application FastAPI.

L'OpenAPI est un livrable a part entiere : le client TypeScript du front en est
genere, et le serveur MCP consomme ce contrat. La CI echoue si le client genere n'est
plus a jour.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from carburant_api import erreurs
from carburant_api.limite import MiddlewareLimite, limite_configuree
from carburant_api.requetes.connexion import creer_pool
from carburant_api.routes import anecdotes, geocode, meta, sante, stations, tendances
from carburant_api.version import DESCRIPTION, PREFIXE, TITRE, VERSION

DELAI_AMONT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0)
"""Timeouts vers les services amont. Courts : une page qui attend 30 secondes un
geocodeur en panne est pire qu'une page qui dit franchement qu'il ne repond pas."""


def origines_autorisees() -> list[str]:
    """Origines autorisees par CORS, lues dans l'environnement.

    Jamais `*` : seules les origines du site sont admises.
    """
    brut = os.environ.get("API_ORIGINES_AUTORISEES", "http://localhost:3000")
    return [origine.strip() for origine in brut.split(",") if origine.strip()]


@asynccontextmanager
async def cycle_de_vie(app: FastAPI) -> AsyncIterator[None]:
    """Ouvre le pool de connexions au demarrage, le ferme a l'arret.

    L'ouverture ne bloque pas le demarrage : si la base n'est pas encore prete,
    l'application demarre quand meme et `/v1/sante` renvoie 503 -- ce qui est la bonne
    reponse, et permet a la sonde de le voir.
    """
    app.state.pool = creer_pool()
    # Un seul client HTTP pour tout le processus : etablir une connexion TLS a chaque
    # geocodage couterait plus cher que le geocodage lui-meme.
    app.state.client_http = httpx.AsyncClient(
        timeout=DELAI_AMONT,
        follow_redirects=True,
        headers={"User-Agent": f"carburant-api/{VERSION} (+https://github.com/bapotuse/carburant)"},
    )
    try:
        await app.state.pool.open(wait=False)
        yield
    finally:
        await app.state.client_http.aclose()
        await app.state.pool.close()


def _documenter_la_limite(app: FastAPI) -> Callable[[], dict[str, Any]]:
    """Declare le 429 sur toutes les routes **sauf celles que le limiteur exempte**.

    Le middleware est transparent pour FastAPI : rien dans les declarations de routes
    ne dit qu'une requete peut etre refusee pour exces de debit. Un client genere
    depuis cet OpenAPI -- le front, le serveur MCP -- n'aurait donc aucune raison de
    prevoir ce cas. On l'injecte apres coup.

    La liste des exemptions est lue dans `MiddlewareLimite.EXEMPTS`, pas recopiee :
    le comportement et sa documentation ne peuvent pas diverger.
    """
    base = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = base()
        for chemin, operations in schema.get("paths", {}).items():
            if chemin in MiddlewareLimite.EXEMPTS:
                continue
            for operation in operations.values():
                if not isinstance(operation, dict) or "responses" not in operation:
                    continue
                operation["responses"].setdefault(
                    "429",
                    {
                        "description": (
                            f"Trop de requetes : la limite est de {limite_configuree()} "
                            "par minute et par adresse. La reponse porte un en-tete "
                            "`Retry-After` en secondes."
                        )
                    },
                )
        app.openapi_schema = schema
        return schema

    return openapi


def creer_app() -> FastAPI:
    """Assemble l'application. Une fonction, pour pouvoir la construire en test."""
    app = FastAPI(
        lifespan=cycle_de_vie,
        title=TITRE,
        description=DESCRIPTION,
        version=VERSION,
        openapi_url=f"{PREFIXE}/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )
    # L'ordre compte : Starlette enveloppe les middlewares dans l'ordre inverse de
    # leur ajout, donc le dernier ajoute est le plus exterieur. CORS doit etre
    # au-dessus de la limitation de debit, sinon un 429 arriverait sans ses en-tetes
    # CORS et le navigateur l'afficherait comme une erreur reseau au lieu du message.
    app.add_middleware(MiddlewareLimite)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origines_autorisees(),
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )
    erreurs.enregistrer(app)
    app.include_router(sante.routeur, prefix=PREFIXE)
    app.include_router(meta.routeur, prefix=PREFIXE)
    app.include_router(geocode.routeur, prefix=PREFIXE)
    app.include_router(stations.routeur, prefix=PREFIXE)
    app.include_router(tendances.routeur, prefix=PREFIXE)
    app.include_router(anecdotes.routeur, prefix=PREFIXE)
    # Apres les routeurs : la fonction doit voir tous les chemins.
    app.openapi = _documenter_la_limite(app)  # type: ignore[method-assign]
    return app


app = creer_app()
