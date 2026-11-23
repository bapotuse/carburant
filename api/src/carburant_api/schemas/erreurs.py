"""Erreurs au format `application/problem+json` (RFC 9457)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Probleme(BaseModel):
    """Corps d'une reponse d'erreur, au format problem+json."""

    type: str = Field(
        default="about:blank",
        description="URI identifiant le type de probleme.",
        examples=["https://carburant/erreurs/lieu-introuvable"],
    )
    title: str = Field(description="Resume court et stable du type de probleme.")
    status: int = Field(description="Code HTTP, repete dans le corps.", examples=[404])
    detail: str = Field(
        description="Explication de cette occurrence precise, exploitable telle quelle.",
        examples=["lieu introuvable : precise la ville ou le code postal"],
    )
    instance: str | None = Field(
        default=None, description="URI de la requete qui a produit l'erreur."
    )
