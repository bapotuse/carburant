"""Serveur MCP : prix des carburants en France.

Deux transports : `stdio` pour une installation locale, et Streamable HTTP pour le
connecteur distant deploye sur le VPS.

Le serveur n'appelle **que l'API publique**, jamais la base de donnees : n'importe qui
peut donc l'installer sans rien avoir a heberger.

Les outils arrivent au Jalon 4. Ce module existe des maintenant pour que le point
d'entree `prix-carburant-mcp`, le conteneur et la route `/mcp` de Caddy soient
testables de bout en bout.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Final

API_PAR_DEFAUT: Final = "https://carburant.example/v1"
"""Production par defaut : le serveur doit marcher sans configuration."""


def base_api() -> str:
    """URL de base de l'API, configurable par variable d'environnement."""
    return os.environ.get("CARBURANT_API_BASE", API_PAR_DEFAUT).rstrip("/")


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entree de la commande `prix-carburant-mcp`."""
    parseur = argparse.ArgumentParser(
        prog="prix-carburant-mcp",
        description="Serveur MCP des prix des carburants en France.",
    )
    parseur.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio pour un client local, http pour le connecteur distant",
    )
    args = parseur.parse_args(argv)
    sys.stderr.write(f"transport '{args.transport}' vers {base_api()} : outils au Jalon 4.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
