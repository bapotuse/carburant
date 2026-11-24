"""Orchestration d'une execution : extract, transform, load, qualite.

Chaque etape est une fonction idempotente, appelee dans l'ordre par `executer`.
Passer a Prefect plus tard consistera a envelopper ces fonctions, pas a les reecrire.

Toute execution laisse une trace dans `meta.execution_etl`, qu'elle reussisse ou non.
C'est de cette table que sortent la fraicheur affichee sur le site et les alertes :
une execution qui echoue sans rien ecrire serait une panne invisible.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from carburant_etl.chargement import marts
from carburant_etl.chargement.staging import charger, ouvrir, purger_staging
from carburant_etl.config import Config
from carburant_etl.modeles import Aplatissement, aplatir
from carburant_etl.sources.flux_v2 import Collecte, purger, telecharger

journal = logging.getLogger("carburant.etl")


@dataclass(frozen=True, slots=True)
class Resultat:
    """Ce qu'une execution a fait, tel qu'il est journalise et affiche."""

    execution_id: int
    collecte_id: int | None
    stations: int
    prix: int
    rejets: int
    inchange: bool
    fichiers_purges: int
    collectes_purgees: int
    marts: marts.ResultatMarts | None = None


def demarrer_execution(connexion: psycopg.Connection[tuple[object, ...]], commande: str) -> int:
    """Ouvre une ligne dans `meta.execution_etl` et renvoie son identifiant."""
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            "INSERT INTO meta.execution_etl (commande) VALUES (%s) RETURNING id",
            (commande,),
        )
        ligne = curseur.fetchone()
    if ligne is None or not isinstance(ligne[0], int):
        raise RuntimeError(f"ouverture d'execution : identifiant inattendu {ligne!r}")
    return ligne[0]


def cloturer_execution(
    connexion: psycopg.Connection[tuple[object, ...]],
    execution_id: int,
    *,
    statut: str,
    lignes_par_etape: dict[str, int] | None = None,
    avertissements: list[dict[str, Any]] | None = None,
    erreur: str | None = None,
) -> None:
    """Ferme une execution. Appelee aussi bien en succes qu'en echec."""
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            """
            UPDATE meta.execution_etl
               SET fin = now(), statut = %s, lignes_par_etape = %s,
                   avertissements = %s, erreur = %s
             WHERE id = %s
            """,
            (
                statut,
                Jsonb(lignes_par_etape or {}),
                Jsonb(avertissements or []),
                erreur[:4000] if erreur else None,
                execution_id,
            ),
        )


def extraire(config: Config) -> Collecte:
    """Telecharge l'export complet du flux."""
    collecte = telecharger(config.repertoire_brut, user_agent=config.user_agent)
    if collecte.inchange:
        journal.info(
            "contenu identique a la collecte precedente (%s octets, sha %s)",
            collecte.octets,
            collecte.sha256[:12],
        )
    else:
        journal.info(
            "telecharge %.1f Mo en %.1f s -> %s",
            collecte.octets / 1e6,
            collecte.duree_secondes,
            collecte.chemin,
        )
    return collecte


def transformer(collecte: Collecte) -> Aplatissement:
    """Lit le fichier brut, valide et aplatit au format long."""
    if collecte.chemin is None:
        raise ValueError("collecte sans fichier : rien a transformer")
    with gzip.open(collecte.chemin, "rb") as flux:
        export = json.load(flux)
    if not isinstance(export, list):
        raise ValueError(f"export inattendu : {type(export).__name__} au lieu d'une liste")

    aplati = aplatir(export)
    journal.info(
        "%d stations, %d lignes de prix, %d rejets",
        len(aplati.stations),
        len(aplati.prix),
        aplati.rejets.total,
    )
    for champ, motif, nombre, exemple in aplati.rejets.lignes():
        journal.warning("rejet : %s / %s x%d (exemple %s)", champ, motif, nombre, exemple)
    return aplati


def collecte_depuis_fichier(chemin: Path) -> Collecte:
    """Reconstruit une `Collecte` a partir d'un fichier brut deja sur disque.

    C'est ce qui permet de **rejouer une transformation sans retelecharger**, la raison
    d'etre du schema `raw` (`docs/specs/donnees.md`). Utile quand une regle de
    transformation change, quand on veut comparer deux versions du code sur la meme
    donnee, ou quand la machine qui charge n'a pas d'acces a Internet.
    """
    donnees = gzip.decompress(chemin.read_bytes())
    horodatage = dt.datetime.fromtimestamp(chemin.stat().st_mtime, tz=dt.UTC)
    return Collecte(
        source="flux-v2",
        url=f"fichier://{chemin}",
        debut=horodatage,
        fin=horodatage,
        octets=len(donnees),
        sha256=hashlib.sha256(donnees).hexdigest(),
        chemin=chemin,
        inchange=False,
    )


def executer(config: Config, *, rejouer: Path | None = None) -> Resultat:
    """Execute une collecte complete.

    Idempotente : relancee dans la foulee, elle constate que le contenu n'a pas change
    et ne recree ni fichier brut ni lignes de staging.

    `rejouer` reprend un fichier brut existant au lieu de telecharger.
    """
    connexion = ouvrir(config.database_url)
    try:
        execution_id = demarrer_execution(connexion, "run")
        try:
            collecte = collecte_depuis_fichier(rejouer) if rejouer is not None else extraire(config)

            if collecte.inchange:
                # Rien de neuf : inutile de recharger 55 000 lignes identiques.
                cloturer_execution(
                    connexion,
                    execution_id,
                    statut="succes",
                    lignes_par_etape={"extract": 0, "transform": 0, "load": 0},
                    avertissements=[{"motif": "contenu inchange depuis la derniere collecte"}],
                )
                return Resultat(
                    execution_id=execution_id,
                    collecte_id=None,
                    stations=0,
                    prix=0,
                    rejets=0,
                    inchange=True,
                    fichiers_purges=0,
                    collectes_purgees=0,
                )

            aplati = transformer(collecte)
            collecte_id = charger(connexion, collecte, aplati, execution_id=execution_id)
            resultat_marts = marts.charger(connexion, collecte_id)

            # La partition DEFAULT doit rester vide : une ligne dedans veut dire
            # qu'une partition manquait au moment de l'insertion.
            orphelines = marts.partition_defaut_vide(connexion)
            if orphelines:
                raise RuntimeError(
                    f"{orphelines} ligne(s) dans la partition DEFAULT de fact_prix : "
                    "une partition mensuelle manquait."
                )

            fichiers = purger(config.repertoire_brut, retention_jours=config.retention_jours)
            collectes = purger_staging(connexion)

            cloturer_execution(
                connexion,
                execution_id,
                statut="succes",
                lignes_par_etape={
                    "extract": aplati.lignes_lues,
                    "transform": len(aplati.prix),
                    "load_staging": len(aplati.prix),
                    "stations_inserees": resultat_marts.stations_inserees,
                    "stations_mises_a_jour": resultat_marts.stations_mises_a_jour,
                    "stations_desactivees": resultat_marts.stations_desactivees,
                    "prix_nouveaux": resultat_marts.prix_inseres,
                    "prix_revus": resultat_marts.prix_revus,
                    "ruptures": resultat_marts.ruptures,
                    "rejets": aplati.rejets.total,
                },
                avertissements=[
                    {"champ": champ, "motif": motif, "occurrences": nombre, "exemple": exemple}
                    for champ, motif, nombre, exemple in aplati.rejets.lignes()
                ],
            )
            return Resultat(
                execution_id=execution_id,
                collecte_id=collecte_id,
                stations=len(aplati.stations),
                prix=len(aplati.prix),
                rejets=aplati.rejets.total,
                inchange=False,
                fichiers_purges=fichiers,
                collectes_purgees=collectes,
                marts=resultat_marts,
            )
        except Exception as erreur:
            cloturer_execution(
                connexion, execution_id, statut="echec", erreur=f"{type(erreur).__name__}: {erreur}"
            )
            raise
    finally:
        connexion.close()
