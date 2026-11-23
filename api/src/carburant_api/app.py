"""Construction de l'application FastAPI.

L'OpenAPI est un livrable a part entiere : le client TypeScript du front en est
genere, et le serveur MCP consomme ce contrat. La CI echoue si le client genere n'est
plus a jour.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from carburant_api.requetes.connexion import creer_pool
from carburant_api.routes import sante
from carburant_api.version import DESCRIPTION, PREFIXE, TITRE, VERSION


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
    try:
        await app.state.pool.open(wait=False)
        yield
    finally:
        await app.state.pool.close()


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origines_autorisees(),
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )
    app.include_router(sante.routeur, prefix=PREFIXE)
    return app


app = creer_app()
