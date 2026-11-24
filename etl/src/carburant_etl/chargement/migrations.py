"""Application des migrations SQL.

Pas d'outil tiers : des fichiers SQL numerotes et une table de suivi suffisent pour un
schema de cette taille, se lisent sans documentation, et s'expliquent en entretien.

Ecrit en Python plutot qu'en bash parce que le meme code doit tourner a trois endroits
qui n'ont pas les memes outils : le poste de developpement (via `docker compose exec`),
le conteneur etl, et le runner de CI (qui n'a ni la pile Compose ni forcement `psql`).
Une seule implementation, une seule chose a maintenir.

Garde-fou : une migration deja appliquee dont le contenu a change fait echouer
l'application plutot que de laisser deux bases diverger en silence.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg

journal = logging.getLogger("carburant.migrations")


def repertoire_par_defaut() -> Path:
    """Ou chercher les fichiers de migration.

    Configurable par `ETL_REPERTOIRE_MIGRATIONS`, parce que l'arborescence n'est pas
    la meme dans le depot et dans l'image : s'appuyer sur un nombre de dossiers
    parents casserait au premier deplacement de fichier.
    """
    depuis_environnement = os.environ.get("ETL_REPERTOIRE_MIGRATIONS")
    if depuis_environnement:
        return Path(depuis_environnement)
    return Path(__file__).resolve().parents[4] / "infra" / "migrations"


class MigrationModifiee(RuntimeError):
    """Une migration deja appliquee a ete modifiee apres coup."""


@dataclass(frozen=True, slots=True)
class Migration:
    """Un fichier de migration, avec l'empreinte de son contenu."""

    nom: str
    chemin: Path
    sha256: str

    @classmethod
    def depuis(cls, chemin: Path) -> Migration:
        contenu = chemin.read_bytes()
        return cls(
            nom=chemin.name,
            chemin=chemin,
            sha256=hashlib.sha256(contenu).hexdigest(),
        )


def lister(repertoire: Path | None = None) -> list[Migration]:
    """Les migrations du repertoire, dans l'ordre de leur numero."""
    dossier = repertoire or repertoire_par_defaut()
    return [Migration.depuis(f) for f in sorted(dossier.glob("*.sql"))]


def _deja_appliquees(
    connexion: psycopg.Connection[tuple[object, ...]],
) -> dict[str, str]:
    """Nom -> empreinte des migrations deja passees.

    La toute premiere migration cree `meta.migration` : on ne peut pas l'interroger
    avant qu'elle existe.
    """
    with connexion.cursor() as curseur:
        curseur.execute("SELECT to_regclass('meta.migration') IS NOT NULL")
        ligne = curseur.fetchone()
        if ligne is None or ligne[0] is not True:
            return {}
        curseur.execute("SELECT nom, sha256 FROM meta.migration")
        return {str(nom): str(somme) for nom, somme in curseur.fetchall()}


def appliquer(database_url: str, repertoire: Path | None = None) -> list[str]:
    """Applique les migrations manquantes. Renvoie les noms appliques.

    Idempotente : relancee, elle ne fait rien.
    """
    migrations = lister(repertoire)
    if not migrations:
        dossier = repertoire or repertoire_par_defaut()
        raise FileNotFoundError(
            f"aucune migration dans {dossier}. Verifier ETL_REPERTOIRE_MIGRATIONS."
        )

    appliquees: list[str] = []
    # autocommit : sans lui, la lecture de `meta.migration` ouvrirait une
    # transaction implicite, et les `with connexion.transaction()` suivants ne
    # seraient que des points de reprise -- ce qui rendrait l'application de N
    # migrations tout-ou-rien, contrairement a ce qui est annonce plus bas.
    with psycopg.connect(database_url, autocommit=True) as connexion:
        connues = _deja_appliquees(connexion)

        for migration in migrations:
            attendue = connues.get(migration.nom)
            if attendue == migration.sha256:
                continue
            if attendue is not None:
                raise MigrationModifiee(
                    f"{migration.nom} a deja ete appliquee mais son contenu a change. "
                    "Ne jamais modifier une migration appliquee : en ajouter une nouvelle."
                )

            journal.info("application de %s", migration.nom)
            # Chaque migration dans sa propre transaction : si la troisieme casse, les
            # deux premieres restent appliquees et enregistrees comme telles.
            with connexion.transaction():
                connexion.execute(migration.chemin.read_bytes())
                connexion.execute(
                    "INSERT INTO meta.migration (nom, sha256) VALUES (%s, %s)",
                    (migration.nom, migration.sha256),
                )
            appliquees.append(migration.nom)

    return appliquees
