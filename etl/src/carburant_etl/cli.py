"""Point d'entree en ligne de commande de l'ETL.

Chaque sous-commande appelle une fonction idempotente. Passer a Prefect plus tard
consistera a envelopper ces fonctions, sans les reecrire.

    etl run                  collecte, transforme, charge, puis controle la qualite
    etl backfill --annee A   amorce l'historique depuis une archive annuelle
    etl refresh              rafraichit les vues materialisees et snapshot_prix_jour
    etl qualite              rejoue les controles qualite sur la derniere collecte
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from carburant_etl.config import PREMIERE_ANNEE_ARCHIVE


def _parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(
        prog="etl",
        description="Prix des carburants en France : collecte et historisation.",
    )
    sous = parseur.add_subparsers(dest="commande", required=True)

    sous.add_parser("run", help="collecte, transforme, charge et controle")

    backfill = sous.add_parser("backfill", help="amorce l'historique depuis une archive")
    backfill.add_argument(
        "--annee",
        type=int,
        required=True,
        help=f"annee de l'archive, depuis {PREMIERE_ANNEE_ARCHIVE}",
    )

    sous.add_parser("refresh", help="rafraichit snapshot_prix_jour et les vues")
    sous.add_parser("qualite", help="rejoue les controles qualite")
    return parseur


def main(argv: Sequence[str] | None = None) -> int:
    """Execute la commande demandee et renvoie le code de sortie du processus."""
    args = _parseur().parse_args(argv)
    # Les etapes arrivent au Jalon 1. La CLI existe des maintenant pour que le
    # Makefile, le conteneur et la planification soient testables.
    sys.stderr.write(f"commande '{args.commande}' reconnue : implementation au Jalon 1.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
