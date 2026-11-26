"""Point d'entree en ligne de commande de l'ETL.

Chaque sous-commande appelle une fonction idempotente. Passer a Prefect plus tard
consistera a envelopper ces fonctions, sans les reecrire.

    etl migrate              applique les migrations SQL manquantes
    etl run                  collecte, transforme, charge, puis controle la qualite
    etl backfill --annee A   amorce l'historique depuis une archive annuelle
    etl refresh              rafraichit les vues materialisees et snapshot_prix_jour
    etl qualite              rejoue les controles qualite sur la derniere collecte
    etl facteurs             recupere les facteurs d emission de la Base Carbone
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
    refresh = sous.add_parser("refresh", help="rafraichit la reference et les agregats")
    refresh.add_argument(
        "--jours",
        type=int,
        default=7,
        help="nombre de jours recents a recalculer ; 0 recalcule tout l historique",
    )
    refresh.add_argument(
        "--annee",
        type=int,
        help="recalcule une annee entiere en une passe (apres un amorcage)",
    )
    sous.add_parser("qualite", help="rejoue les controles qualite")
    # Pas dans la boucle de quinze minutes : la Base Carbone bouge une fois par an.
    sous.add_parser("facteurs", help="recupere les facteurs d emission de l ADEME")
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
    from carburant_etl.pipeline import EchecQualite, executer

    try:
        resultat = executer(Config.depuis_environnement(), rejouer=rejouer)
    except EchecQualite as echec:
        # Les donnees sont chargees et l'execution est deja journalisee en echec.
        # On sort en erreur pour que le planificateur et l'alerte le sachent.
        for verdict in echec.echecs:
            print(f"qualite [ECHEC] {verdict.nom} : {verdict.mesure}", file=sys.stderr)
        return 1

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
    if resultat.qualite is not None:
        echecs = [v for v in resultat.qualite if not v.ok]
        if echecs:
            for verdict in echecs:
                print(
                    f"qualite [{'ECHEC' if verdict.bloquant else 'alerte'}] "
                    f"{verdict.nom} : {verdict.mesure}"
                )
        else:
            print(f"qualite : {len(resultat.qualite)} controles, tous au vert.")
    if resultat.fichiers_purges or resultat.collectes_purgees:
        print(
            f"purge : {resultat.fichiers_purges} fichier(s) brut(s), "
            f"{resultat.collectes_purgees} collecte(s) de staging."
        )
    return 0


def _backfill(annee: int) -> int:
    """Charge une annee d archive dans l historique."""
    from carburant_etl.chargement.backfill import amorcer
    from carburant_etl.chargement.staging import ouvrir

    config = Config.depuis_environnement()
    connexion = ouvrir(config.database_url)
    try:
        resultat = amorcer(
            connexion,
            annee,
            repertoire=config.repertoire_brut,
            user_agent=config.user_agent,
        )
    finally:
        connexion.close()

    print(
        f"archive {resultat.annee} : {resultat.stations_lues} stations "
        f"({resultat.stations_creees} nouvelle(s)), {resultat.prix_lus} prix lus, "
        f"{resultat.prix_inseres} insere(s), {resultat.prix_deja_connus} deja connu(s), "
        f"en {resultat.duree_secondes:.0f} s."
    )
    if resultat.partitions_creees:
        print(f"partitions creees : {len(resultat.partitions_creees)}")
    rejets = {c: n for c, n in resultat.rejets.items() if c != "exemples" and n}
    if rejets:
        print("rejets : " + ", ".join(f"{motif} {nombre}" for motif, nombre in rejets.items()))
    return 0


def _refresh(jours: int | None, annee: int | None) -> int:
    """Rafraichit la reference departementale et les agregats journaliers.

    Avec `--annee`, recalcule l annee entiere en une passe : c est ce qu il faut
    apres un amorcage, ou rejouer jour par jour voudrait dire 365 requetes.
    """
    import datetime as dt

    from carburant_etl.chargement import agregats
    from carburant_etl.chargement.staging import ouvrir

    connexion = ouvrir(Config.depuis_environnement().database_url)
    try:
        if annee is not None:
            lignes = agregats.calculer_periode(
                connexion, dt.date(annee, 1, 1), dt.date(annee, 12, 31)
            )
            print(f"annee {annee} : {lignes} ligne(s) d agregat.")
            return 0
        resultat = agregats.rafraichir(connexion, jours=jours)
    finally:
        connexion.close()
    print(
        f"reference departementale rafraichie ; "
        f"{resultat.lignes_agregat} ligne(s) d agregat sur {resultat.jours} jour(s)."
    )
    return 0


def _facteurs() -> int:
    """Recupere les facteurs d emission de la Base Carbone et les historise.

    Volontairement hors de la boucle de collecte : la Base Carbone bouge une fois
    par an, interroger l ADEME toutes les quinze minutes n aurait aucun sens.
    """
    from carburant_etl.chargement.facteurs import charger
    from carburant_etl.chargement.staging import ouvrir
    from carburant_etl.sources.ademe import recuperer

    config = Config.depuis_environnement()
    facteurs = recuperer(config.user_agent)
    connexion = ouvrir(config.database_url)
    try:
        resultat = charger(connexion, facteurs)
    finally:
        connexion.close()

    for facteur in facteurs:
        libelle = facteur.nom_base + (f" / {facteur.nom_attribut}" if facteur.nom_attribut else "")
        print(f"  {facteur.carburant:7s} {facteur.valeur:6.3f} {facteur.unite}  {libelle}")
    print(
        f"version {resultat.version} : {resultat.nouveaux} facteur(s) ajoute(s), "
        f"{resultat.deja_connus} deja connu(s)."
    )
    return 0


def _qualite() -> int:
    """Rejoue les controles qualite sur l'etat courant de la base."""
    from carburant_etl.chargement.staging import ouvrir
    from carburant_etl.qualite import controles

    connexion = ouvrir(Config.depuis_environnement().database_url)
    try:
        verdicts = controles.executer(connexion)
    finally:
        connexion.close()

    for verdict in verdicts:
        marque = "ok " if verdict.ok else ("ECHEC" if verdict.bloquant else "alerte")
        print(f"[{marque}] {verdict.nom} : {verdict.mesure}")
    print(controles.resume(verdicts))
    return 1 if controles.echecs_bloquants(verdicts) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Execute la commande demandee et renvoie le code de sortie du processus."""
    args = _parseur().parse_args(argv)
    _configurer_journal(args.verbeux)

    if args.commande == "run":
        return _run(args.rejouer)
    if args.commande == "migrate":
        return _migrate()
    if args.commande == "qualite":
        return _qualite()
    if args.commande == "refresh":
        return _refresh(args.jours if args.jours > 0 else None, args.annee)
    if args.commande == "facteurs":
        return _facteurs()
    if args.commande == "backfill":
        return _backfill(args.annee)

    sys.stderr.write(f"commande inconnue : {args.commande}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
