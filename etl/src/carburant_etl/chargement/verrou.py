"""Verrou d'exclusion entre executions de l'ETL.

Le probleme, observe le 26/11/2026 : l'amorçage de l'historique dure une heure, et
supercronic lance une collecte toutes les quinze minutes. Quatre collectes se sont
donc superposees a un amorcage en cours. Rien n'a casse -- les deux sont
idempotents, et PostgreSQL serialise les transactions -- mais c'est de la chance,
pas une garantie :

- l'amorcage cree les partitions d'une annee pendant qu'une collecte cree celles du
  mois courant : deux `CREATE TABLE … PARTITION OF` concurrents sur la meme table
  parente se bloquent, et l'un des deux peut echouer sur un conflit ;
- `REFRESH MATERIALIZED VIEW CONCURRENTLY` refuse de tourner deux fois en meme
  temps ;
- et surtout, deux executions se partagent la bande passante et le disque d'un VPS
  a 10 Go de RAM, pour un travail qui aurait ete fait de toute facon.

Un `pg_advisory_lock` repond exactement a cela : un verrou porte par la base, pas
par un fichier ni par un processus, donc valable entre conteneurs et entre machines,
et **libere automatiquement a la fin de la session** -- un conteneur tue par le
noyau ne laisse pas un verrou orphelin derriere lui, contrairement a un fichier.

C'est `pg_try_advisory_lock` et non `pg_advisory_lock` : on ne veut pas qu'une
collecte attende une heure la fin d'un amorcage. Elle renonce, le dit, et la
suivante passera dans quinze minutes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

import psycopg

journal = logging.getLogger("carburant.verrou")

CLE: Final = 0x43415242  # « CARB » en hexadecimal : lisible dans pg_locks.
"""Identifiant du verrou. Une seule cle pour tout l'ETL : collecte, amorcage et
rafraichissement s'excluent mutuellement, parce qu'ils touchent les memes tables."""


class DejaEnCours(RuntimeError):
    """Une autre execution de l'ETL detient le verrou."""


@contextmanager
def exclusif(
    connexion: psycopg.Connection[tuple[object, ...]], *, operation: str
) -> Iterator[None]:
    """Prend le verrou pour la duree du bloc, ou leve `DejaEnCours`.

    Le verrou est pose sur **cette** connexion : il tombe de lui-meme si le
    processus meurt, sans menage a faire.
    """
    with connexion.cursor() as curseur:
        curseur.execute("SELECT pg_try_advisory_lock(%s)", (CLE,))
        ligne = curseur.fetchone()
    obtenu = bool(ligne[0]) if ligne else False

    if not obtenu:
        with connexion.cursor() as curseur:
            # Qui le detient ? Sans cela, « deja en cours » n'aide personne a
            # comprendre ce qui se passe sur la machine.
            curseur.execute(
                """
                SELECT a.application_name, a.query_start, left(a.query, 80)
                  FROM pg_locks l
                  JOIN pg_stat_activity a ON a.pid = l.pid
                 WHERE l.locktype = 'advisory' AND l.objid = %s AND l.granted
                 LIMIT 1
                """,
                (CLE,),
            )
            detenteur = curseur.fetchone()
        detail = f" (depuis {detenteur[1]})" if detenteur else ""
        raise DejaEnCours(
            f"{operation} : une autre execution de l ETL est en cours{detail}. "
            "On renonce plutot que d attendre : la prochaine collecte passera."
        )

    journal.debug("verrou pris pour %s", operation)
    try:
        yield
    finally:
        with connexion.cursor() as curseur:
            curseur.execute("SELECT pg_advisory_unlock(%s)", (CLE,))
        journal.debug("verrou rendu apres %s", operation)
