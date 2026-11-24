"""Erreurs au format `application/problem+json` (RFC 9457).

Une erreur doit etre exploitable telle quelle, par un humain comme par un modele de
langage : le serveur MCP relaie ces messages a un assistant, et « 422 Unprocessable
Entity » ne lui apprend rien. Chaque probleme porte donc un `detail` qui dit ce qui
ne va pas **et** ce qu'il faut faire.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

TYPE_MIME: Final = "application/problem+json"
BASE_TYPE: Final = "https://github.com/bapotuse/carburant/blob/main/docs/specs/api-mcp.md"


class ProblemeAPI(Exception):
    """Une erreur metier, destinee a etre rendue en problem+json."""

    def __init__(
        self,
        *,
        statut: int,
        titre: str,
        detail: str,
        type_: str = "about:blank",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.statut = statut
        self.titre = titre
        self.detail = detail
        self.type_ = type_
        self.extra = extra or {}
        super().__init__(detail)


def _reponse(
    requete: Request,
    *,
    statut: int,
    titre: str,
    detail: str,
    type_: str = "about:blank",
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    corps: dict[str, Any] = {
        "type": type_,
        "title": titre,
        "status": statut,
        "detail": detail,
        "instance": str(requete.url.path),
    }
    corps.update(extra or {})
    return JSONResponse(status_code=statut, content=corps, media_type=TYPE_MIME)


def _lisible(erreur: dict[str, Any]) -> str:
    """Transforme une erreur de validation pydantic en phrase utile.

    `['query', 'rayon_km'] / Input should be less than or equal to 50` devient
    « rayon_km : Input should be less than or equal to 50 ». On garde le message de
    pydantic, qui est precis, mais on nomme le parametre fautif en clair.
    """
    emplacement = [str(p) for p in erreur.get("loc", []) if p not in ("query", "body", "path")]
    nom = ".".join(emplacement) or "requete"
    return f"{nom} : {erreur.get('msg', 'valeur invalide')}"


def enregistrer(app: FastAPI) -> None:
    """Branche les gestionnaires d'erreur sur l'application."""

    @app.exception_handler(ProblemeAPI)
    async def _probleme(requete: Request, erreur: ProblemeAPI) -> JSONResponse:
        return _reponse(
            requete,
            statut=erreur.statut,
            titre=erreur.titre,
            detail=erreur.detail,
            type_=erreur.type_,
            extra=erreur.extra,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(requete: Request, erreur: RequestValidationError) -> JSONResponse:
        details = [_lisible(e) for e in erreur.errors()]
        return _reponse(
            requete,
            statut=status.HTTP_422_UNPROCESSABLE_CONTENT,
            titre="Parametres invalides",
            detail=" ; ".join(details) or "la requete n'a pas pu etre validee",
            type_=f"{BASE_TYPE}#parametres-invalides",
            extra={"erreurs": details},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(requete: Request, erreur: StarletteHTTPException) -> JSONResponse:
        titres = {
            status.HTTP_404_NOT_FOUND: "Ressource introuvable",
            status.HTTP_405_METHOD_NOT_ALLOWED: "Methode non autorisee",
            status.HTTP_429_TOO_MANY_REQUESTS: "Trop de requetes",
        }
        return _reponse(
            requete,
            statut=erreur.status_code,
            titre=titres.get(erreur.status_code, "Erreur"),
            detail=str(erreur.detail),
        )
