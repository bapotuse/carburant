"""Chargement du staging par `COPY`.

`COPY` et non des `INSERT` : c'est l'ordre de chargement en masse de PostgreSQL, et
l'ecart n'est pas marginal. Mesure du 23/11/2026 sur l'archive annuelle, 5 297 799
lignes chargees en 14 secondes, soit environ 380 000 lignes par seconde.

Une execution ecrit, dans une seule transaction :

1. une ligne dans `raw.collecte` (la trace du telechargement) ;
2. les stations dans `staging.station` ;
3. les prix dans `staging.prix`, au format long ;
4. les rejets de validation dans `staging.rejet`.

Tout ou rien : si le chargement casse a mi-course, la collecte n'existe pas, et il n'y
a pas de staging a moitie rempli a nettoyer a la main.
"""

from __future__ import annotations

from typing import Final

import psycopg
from psycopg.types.json import Jsonb

from carburant_etl.modeles import Aplatissement
from carburant_etl.sources.flux_v2 import Collecte

COLONNES_STATION: Final = (
    "collecte_id, station_id, longitude, latitude, cp, adresse, ville, pop, "
    "departement, code_departement, region, code_region, horaires, services"
)

COLONNES_PRIX: Final = "collecte_id, station_id, carburant, prix, maj, rupture_type, rupture_debut"

COLONNES_REJET: Final = "collecte_id, champ, motif, occurrences, exemple"


def ouvrir(database_url: str) -> psycopg.Connection[tuple[object, ...]]:
    """Ouvre une connexion en **autocommit**, avec des transactions explicites.

    `autocommit=True` n'a rien de laxiste ici : c'est ce qui rend les transactions
    previsibles. En mode non-autocommit, psycopg ouvre une transaction implicite des
    le premier ordre -- y compris un simple `SELECT`. Tous les
    `with connexion.transaction()` qui suivent ne sont alors que des points de
    reprise imbriques : ils ne valident rien, et un `close()` annule tout.

    Le defaut etait reel et silencieux : un controle qualite en lecture, place entre
    le chargement et la cloture de l'execution, laissait `meta.execution_etl` bloque
    sur `en_cours` pour toujours -- donc `/v1/sante` et `/v1/meta` annoncaient qu'il
    n'y avait jamais eu de collecte reussie, alors que les donnees etaient bien la.

    En autocommit, une lecture n'ouvre rien, et chaque `with connexion.transaction()`
    est une vraie transaction, validee a la sortie du bloc.
    """
    return psycopg.connect(database_url, autocommit=True)


def enregistrer_collecte(
    connexion: psycopg.Connection[tuple[object, ...]],
    collecte: Collecte,
    *,
    execution_id: int | None = None,
) -> int:
    """Insere la trace du telechargement et renvoie son identifiant."""
    with connexion.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO raw.collecte
                (source, url, debut, fin, octets, sha256, chemin, inchange,
                 statut, execution_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'en_cours', %s)
            RETURNING id
            """,
            (
                collecte.source,
                collecte.url,
                collecte.debut,
                collecte.fin,
                collecte.octets,
                collecte.sha256,
                str(collecte.chemin) if collecte.chemin is not None else None,
                collecte.inchange,
                execution_id,
            ),
        )
        ligne = curseur.fetchone()
    # `fetchone` rend `tuple[object, ...] | None` : on verifie plutot que de forcer le
    # type, pour que le jour ou la requete change, l'erreur soit lisible.
    if ligne is None or not isinstance(ligne[0], int):
        raise RuntimeError(f"insertion dans raw.collecte : identifiant inattendu {ligne!r}")
    return ligne[0]


def charger(
    connexion: psycopg.Connection[tuple[object, ...]],
    collecte: Collecte,
    aplati: Aplatissement,
    *,
    execution_id: int | None = None,
) -> int:
    """Charge une collecte complete en staging. Renvoie l'identifiant de collecte.

    Transactionnel : la collecte n'apparait en base que si tout a ete charge.
    """
    with connexion.transaction():
        collecte_id = enregistrer_collecte(connexion, collecte, execution_id=execution_id)
        _copier_stations(connexion, collecte_id, aplati)
        _copier_prix(connexion, collecte_id, aplati)
        _copier_rejets(connexion, collecte_id, aplati)

        with connexion.cursor() as curseur:
            curseur.execute(
                "UPDATE raw.collecte SET statut = 'succes', lignes = %s WHERE id = %s",
                (len(aplati.prix), collecte_id),
            )
    return collecte_id


def marquer_echec(
    connexion: psycopg.Connection[tuple[object, ...]],
    collecte_id: int,
    erreur: str,
) -> None:
    """Marque une collecte en echec, avec sa cause. Jamais de collecte muette."""
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            "UPDATE raw.collecte SET statut = 'echec', erreur = %s WHERE id = %s",
            (erreur[:2000], collecte_id),
        )


def _copier_stations(
    connexion: psycopg.Connection[tuple[object, ...]],
    collecte_id: int,
    aplati: Aplatissement,
) -> None:
    requete = f"COPY staging.station ({COLONNES_STATION}) FROM STDIN"
    with connexion.cursor() as curseur, curseur.copy(requete) as copie:
        for s in aplati.stations:
            copie.write_row(
                (
                    collecte_id,
                    s.station_id,
                    s.longitude,
                    s.latitude,
                    s.cp,
                    s.adresse,
                    s.ville,
                    s.pop,
                    s.departement,
                    s.code_departement,
                    s.region,
                    s.code_region,
                    # `Jsonb` et non une chaine : psycopg adapte lui-meme, ce qui evite
                    # d'avoir a echapper quoi que ce soit a la main.
                    Jsonb(s.horaires) if s.horaires is not None else None,
                    s.services,
                )
            )


def _copier_prix(
    connexion: psycopg.Connection[tuple[object, ...]],
    collecte_id: int,
    aplati: Aplatissement,
) -> None:
    requete = f"COPY staging.prix ({COLONNES_PRIX}) FROM STDIN"
    with connexion.cursor() as curseur, curseur.copy(requete) as copie:
        for p in aplati.prix:
            copie.write_row(
                (
                    collecte_id,
                    p.station_id,
                    p.carburant,
                    p.prix,
                    p.maj,
                    p.rupture_type,
                    p.rupture_debut,
                )
            )


def _copier_rejets(
    connexion: psycopg.Connection[tuple[object, ...]],
    collecte_id: int,
    aplati: Aplatissement,
) -> None:
    lignes = aplati.rejets.lignes()
    if not lignes:
        return
    requete = f"COPY staging.rejet ({COLONNES_REJET}) FROM STDIN"
    with connexion.cursor() as curseur, curseur.copy(requete) as copie:
        for champ, motif, occurrences, exemple in lignes:
            copie.write_row((collecte_id, champ, motif, occurrences, exemple))


def purger_staging(
    connexion: psycopg.Connection[tuple[object, ...]],
    *,
    collectes_a_garder: int = 4,
) -> int:
    """Ne garde en staging que les N dernieres collectes reussies.

    Le staging est un sas, pas un entrepot : l'historique vit dans `marts`. En garder
    quelques-unes permet de rejouer une transformation ou de comparer deux collectes
    sans laisser la table grossir indefiniment -- 55 000 lignes toutes les 15 minutes
    feraient 5,3 millions de lignes par jour.

    Renvoie le nombre de collectes supprimees. Le `ON DELETE CASCADE` emporte les
    lignes de staging correspondantes.
    """
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            """
            DELETE FROM raw.collecte
            WHERE id NOT IN (
                SELECT id FROM raw.collecte
                WHERE statut = 'succes'
                ORDER BY debut DESC
                LIMIT %s
            )
            AND statut = 'succes'
            """,
            (collectes_a_garder,),
        )
        return curseur.rowcount
