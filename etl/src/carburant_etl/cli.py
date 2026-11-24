"""Point d'entree en ligne de commande de l'ETL.

Chaque sous-commande appelle une fonction idempotente. Passer a Prefect plus tard
consistera a envelopper ces fonctions, sans les reecrire.

    etl migrate              applique les migrations SQL manquantes
    etl run                  collecte, transforme, charge, puis controle la qualite
    etl backfill --annee A   amorce l'historique depuis une archive annuelle
    etl refresh              rafraichit les vues materialisees et snapshot_prix_jour
    etl qualite              rejoue les controles qualite sur la derniere collecte
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from carburant_etl.config import PREMIERE_ANNEE_ARCHIVE, Config


def _parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(
        prog="etl",
        description="Prix des carburants en France : collecte et historisation.",
    )
    parseur.add_argument("-v", "--verbeux", action="store_true", help="journaux de niveau debug")
    sous = parseur.add_subparsers(dest="commande", required=True)

    run = sous.add_parser("run", help="collecte, transforme, charge et controle")
    run.add_argument(
        "--rejouer",
        type=Path,
        metavar="FICHIER",
        help=(
            "rejoue la transformation depuis un fichier brut deja telecharge, "
            "au lieu d'interroger la source"
        ),
    )

    backfill = sous.add_parser("backfill", help="amorce l'historique depuis une archive")
    backfill.add_argument(
        "--annee",
        type=int,
        required=True,
        help=f"annee de l'archive, depuis {PREMIERE_ANNEE_ARCHIVE}",
    )

    sous.add_parser("migrate", help="applique les migrations SQL manquantes")
    sous.add_parser("refresh", help="rafraichit snapshot_prix_jour et les vues")
    sous.add_parser("qualite", help="rejoue les controles qualite")
    return parseur


def _configurer_journal(verbeux: bool) -> None:
    """Journaux sur stdout, au format attendu d'un conteneur."""
    logging.basicConfig(
        level=logging.DEBUG if verbeux else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
    )


def _migrate() -> int:
    """Applique les migrations SQL manquantes."""
    from carburant_etl.chargement.migrations import appliquer

    appliquees = appliquer(Config.depuis_environnement().database_url)
    if not appliquees:
        print("Base a jour : aucune migration a appliquer.")
    else:
        for nom in appliquees:
            print(f"-> {nom}")
        print(f"{len(appliquees)} migration(s) appliquee(s).")
    return 0


def _run(rejouer: Path | None) -> int:
    """Collecte, transforme, charge, puis controle."""
    # Import tardif : `etl --help` ne doit pas avoir besoin d'une base joignable.
    from carburant_etl.pipeline import executer

    resultat = executer(Config.depuis_environnement(), rejouer=rejouer)

    if resultat.inchange:
        print("contenu inchange depuis la derniere collecte : rien a charger.")
        return 0

    print(
        f"collecte #{resultat.collecte_id} : {resultat.stations} stations, "
        f"{resultat.prix} lignes de prix, {resultat.rejets} rejets."
    )
    if resultat.marts is not None:
        m = resultat.marts
        print(
            f"marts : {m.stations_inserees} station(s) nouvelle(s), "
            f"{m.stations_mises_a_jour} mise(s) a jour, "
            f"{m.stations_desactivees} desactivee(s) ; "
            f"{m.prix_inseres} changement(s) de prix nouveau(x), "
            f"{m.prix_revus} deja connu(s) ; {m.ruptures} rupture(s)."
        )
        if m.partitions_creees:
            print(f"partitions creees : {', '.join(m.partitions_creees)}")
    if resultat.fichiers_purges or resultat.collectes_purgees:
        print(
            f"purge : {resultat.fichiers_purges} fichier(s) brut(s), "
            f"{resultat.collectes_purgees} collecte(s) de staging."
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Execute la commande demandee et renvoie le code de sortie du processus."""
    args = _parseur().parse_args(argv)
    _configurer_journal(args.verbeux)

    if args.commande == "run":
        return _run(args.rejouer)
    if args.commande == "migrate":
        return _migrate()

    # backfill, refresh et qualite arrivent aux Jalons 1 et 2.
    sys.stderr.write(f"commande '{args.commande}' : implementation a venir.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
