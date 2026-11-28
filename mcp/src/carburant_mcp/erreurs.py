"""Faire remonter nos messages jusqu'à l'assistant, sans les perdre en route.

Le SDK distingue deux sortes d'échecs, et la distinction nous concerne directement :

- `ToolError` est relayée au client **avec son message**. C'est l'échec attendu, celui
  que le modèle doit lire et corriger : un carburant inconnu, un lieu ambigu, une API
  momentanément indisponible.
- toute autre exception devient `UnexpectedToolError("Error executing tool <nom>")`.
  Le message d'origine est perdu, et c'est voulu : un plantage ne doit pas exposer
  l'intérieur du serveur.

Nos messages sont écrits pour être lus par un modèle — ils disent quoi faire, pas
seulement ce qui ne va pas. Les laisser passer par la seconde porte les effacerait, et
l'assistant répondrait « une erreur s'est produite » à quelqu'un qui cherche de
l'essence.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from mcp.server.mcpserver.exceptions import ToolError

from carburant_mcp.carburants import CarburantAmbigu, CarburantInconnu
from carburant_mcp.client import ErreurAPI
from carburant_mcp.lieux import LieuAmbigu, LieuIntrouvable

RELAYEES: Final = (
    CarburantAmbigu,
    CarburantInconnu,
    ErreurAPI,
    LieuAmbigu,
    LieuIntrouvable,
)
"""Les échecs dont le message est utile à l'assistant.

Tout le reste est un défaut de notre côté et doit remonter tel quel : l'avaler ici
transformerait un bogue en « demande invalide », et personne n'irait le chercher.
"""


@contextmanager
def relayer() -> Iterator[None]:
    """Convertit nos exceptions connues en `ToolError`, qui conserve le message.

    Fonctionne autour d'un `await` : l'exception traverse le `with` comme n'importe
    quelle autre, donc un gestionnaire synchrone suffit et évite d'envelopper les
    fonctions, ce qui brouillerait la signature dont le SDK déduit le schéma d'entrée.
    """
    try:
        yield
    except RELAYEES as erreur:
        raise ToolError(str(erreur)) from erreur
