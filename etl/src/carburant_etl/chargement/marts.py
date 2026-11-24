"""Chargement de staging vers marts.

Tout se passe en SQL : les ensembles sont deja en base, les faire transiter par Python
pour les y remettre serait du gaspillage. Le code Python se contente d'orchestrer et de
compter.

Le grain de `fact_prix` est **un changement de prix**. L'idempotence en decoule
directement : une relance retrouve les memes `(station, carburant, maj)` et ne touche
que `derniere_observation`. C'est le critere de sortie du Jalon 1 -- deux executions
successives ne creent aucun doublon.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import psycopg
from psycopg import sql

from carburant_etl.fuseau import bornes_du_mois_utc

journal = logging.getLogger("carburant.marts")

COLLECTES_MANQUEES_AVANT_INACTIVE = 8
"""Une station absente de 8 collectes consecutives (2 heures) devient inactive.

Elle n'est jamais supprimee : son historique de prix reste consultable, et elle
redevient active si elle reapparait. Deux heures, parce qu'une absence d'une ou deux
collectes est le bruit normal d'une source qui se republie toutes les 15 minutes.
"""


def _compte(ligne: tuple[object, ...] | None, index: int = 0) -> int:
    """Lit un `count(*)` dans une ligne de resultat.

    `fetchone` rend `tuple[object, ...]` : on verifie le type plutot que de le forcer,
    pour que l'erreur reste lisible le jour ou la requete change.
    """
    if ligne is None:
        return 0
    valeur = ligne[index]
    if valeur is None:
        return 0
    if not isinstance(valeur, int):
        raise TypeError(f"comptage inattendu : {valeur!r}")
    return valeur


@dataclass(frozen=True, slots=True)
class ResultatMarts:
    """Ce que le chargement vers marts a produit."""

    stations_inserees: int
    stations_mises_a_jour: int
    stations_desactivees: int
    prix_inseres: int
    prix_revus: int
    ruptures: int
    partitions_creees: list[str]


# ---------------------------------------------------------------- partitions


def nom_partition(annee: int, mois: int) -> str:
    return f"fact_prix_{annee:04d}{mois:02d}"


def assurer_partitions(
    connexion: psycopg.Connection[tuple[object, ...]],
    mois: set[tuple[int, int]],
) -> list[str]:
    """Cree les partitions mensuelles manquantes. Renvoie les noms crees.

    **Les bornes sont calculees en UTC.** PostgreSQL interprete les bornes d'une
    partition `timestamptz` en UTC : ecrire `FROM ('2025-01-01')` sans fuseau fait
    tomber les prix du 1er janvier entre 00h00 et 00h58 heure de Paris dans la
    partition precedente, ou dans la partition DEFAULT si elle n'existe pas. Mesure :
    3 612 lignes de l'archive 2025 (docs/reconnaissance.md section 2.5).

    On cree les partitions couvrant **la plage reelle des dates presentes**, et pas
    seulement le mois courant et le suivant comme le proposait la specification :
    `maj` est la date du dernier *changement* de prix, qui peut remonter a plus d'un
    an (483 jours constates pour le SP95). S'en tenir au mois courant remplirait la
    partition DEFAULT, qui doit rester vide.
    """
    creees: list[str] = []
    for annee, numero in sorted(mois):
        nom = nom_partition(annee, numero)
        debut, fin = bornes_du_mois_utc(annee, numero)
        with connexion.cursor() as curseur:
            curseur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"marts.{nom}",))
            ligne = curseur.fetchone()
            if ligne is not None and ligne[0] is True:
                continue
            # PostgreSQL n'accepte pas de parametres liaison dans du DDL :
            # `FOR VALUES FROM (%s)` echoue sur « there is no parameter $1 ». On
            # compose donc la requete avec `psycopg.sql`, qui echappe identifiants et
            # litteraux -- jamais de concatenation de chaines.
            curseur.execute(
                sql.SQL(
                    "CREATE TABLE {table} PARTITION OF marts.fact_prix "
                    "FOR VALUES FROM ({debut}) TO ({fin})"
                ).format(
                    table=sql.Identifier("marts", nom),
                    debut=sql.Literal(debut),
                    fin=sql.Literal(fin),
                )
            )
        creees.append(nom)
        journal.info("partition %s creee : [%s, %s)", nom, debut.isoformat(), fin.isoformat())
    return creees


def mois_presents(
    connexion: psycopg.Connection[tuple[object, ...]], collecte_id: int
) -> set[tuple[int, int]]:
    """Les mois UTC couverts par les dates de mise a jour d'une collecte.

    On y ajoute toujours le mois courant et le suivant : la prochaine collecte verra
    des changements de prix tout frais, et la partition doit deja exister.
    """
    with connexion.cursor() as curseur:
        curseur.execute(
            """
            SELECT DISTINCT
                   extract(year  FROM maj AT TIME ZONE 'UTC')::int,
                   extract(month FROM maj AT TIME ZONE 'UTC')::int
              FROM staging.prix
             WHERE collecte_id = %s AND maj IS NOT NULL
            """,
            (collecte_id,),
        )
        mois = {(_compte(ligne, 0), _compte(ligne, 1)) for ligne in curseur.fetchall()}

    maintenant = dt.datetime.now(tz=dt.UTC)
    mois.add((maintenant.year, maintenant.month))
    suivant = (maintenant.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    mois.add((suivant.year, suivant.month))
    return mois


def partition_defaut_vide(
    connexion: psycopg.Connection[tuple[object, ...]],
) -> int:
    """Nombre de lignes dans la partition DEFAULT. Doit valoir zero.

    Une ligne ici veut dire qu'une partition manquait au moment de l'insertion. Le
    controle qualite en fait echouer l'execution.
    """
    with connexion.cursor() as curseur:
        curseur.execute("SELECT count(*) FROM marts.fact_prix_defaut")
        ligne = curseur.fetchone()
    return _compte(ligne)


# ---------------------------------------------------------------- dimensions


def charger_stations(
    connexion: psycopg.Connection[tuple[object, ...]], collecte_id: int
) -> tuple[int, int]:
    """Met a jour `dim_station` depuis le staging. SCD de type 1.

    Renvoie (inserees, mises a jour). Une station deja connue garde sa `premiere_vue`
    et voit sa `derniere_vue` avancer ; son compteur d'absence est remis a zero et
    elle redevient active si elle etait tombee.

    Le compte des deja-connues se fait avant l'upsert. On pourrait croire plus malin
    de renvoyer `xmax = 0` depuis le `RETURNING`, mais PostgreSQL refuse de lire une
    colonne systeme dans ce contexte -- et compter d'abord se lit mieux.
    """
    with connexion.cursor() as curseur:
        curseur.execute(
            """
            SELECT count(*)
              FROM staging.station s
              JOIN marts.dim_station d ON d.id = s.station_id
             WHERE s.collecte_id = %s
            """,
            (collecte_id,),
        )
        deja_connues = _compte(curseur.fetchone())

        curseur.execute(
            """
            INSERT INTO marts.dim_station AS d
                (id, geom, cp, adresse, ville, departement, code_departement,
                 region, code_region, autoroute, horaires, services,
                 premiere_vue, derniere_vue, active, collectes_manquees)
            SELECT s.station_id,
                   ST_SetSRID(ST_MakePoint(s.longitude, s.latitude), 4326)::geography,
                   s.cp, s.adresse, s.ville, s.departement, s.code_departement,
                   s.region, s.code_region, s.pop = 'A', s.horaires, s.services,
                   c.debut, c.debut, true, 0
              FROM staging.station s
              JOIN raw.collecte c ON c.id = s.collecte_id
             WHERE s.collecte_id = %s
            ON CONFLICT (id) DO UPDATE SET
                   geom               = EXCLUDED.geom,
                   cp                 = EXCLUDED.cp,
                   adresse            = EXCLUDED.adresse,
                   ville              = EXCLUDED.ville,
                   departement        = EXCLUDED.departement,
                   code_departement   = EXCLUDED.code_departement,
                   region             = EXCLUDED.region,
                   code_region        = EXCLUDED.code_region,
                   autoroute          = EXCLUDED.autoroute,
                   horaires           = EXCLUDED.horaires,
                   services           = EXCLUDED.services,
                   derniere_vue       = EXCLUDED.derniere_vue,
                   active             = true,
                   collectes_manquees = 0
            """,
            (collecte_id,),
        )
        touchees = curseur.rowcount

    return touchees - deja_connues, deja_connues


def marquer_absentes(connexion: psycopg.Connection[tuple[object, ...]], collecte_id: int) -> int:
    """Incremente le compteur d'absence, et desactive au-dela du seuil.

    Aucune station n'est jamais supprimee : son historique de prix doit rester
    consultable, et une station fermee pour travaux reapparait.
    """
    with connexion.cursor() as curseur:
        curseur.execute(
            """
            UPDATE marts.dim_station d
               SET collectes_manquees = d.collectes_manquees + 1,
                   active = (d.collectes_manquees + 1) < %s
             WHERE d.active
               AND NOT EXISTS (
                   SELECT 1 FROM staging.station s
                    WHERE s.collecte_id = %s AND s.station_id = d.id
               )
            """,
            (COLLECTES_MANQUEES_AVANT_INACTIVE, collecte_id),
        )
        touchees = curseur.rowcount
        curseur.execute("SELECT count(*) FROM marts.dim_station WHERE NOT active")
        ligne = curseur.fetchone()
    journal.info(
        "%d station(s) absente(s) de cette collecte, %s inactive(s) au total",
        touchees,
        ligne[0] if ligne else "?",
    )
    return touchees


# ---------------------------------------------------------------- faits


def charger_prix(
    connexion: psycopg.Connection[tuple[object, ...]], collecte_id: int
) -> tuple[int, int]:
    """Charge les changements de prix. Renvoie (nouveaux, revus).

    `ON CONFLICT DO UPDATE` sur la seule `derniere_observation` : c'est ce qui rend
    l'operation idempotente. Relancer la meme collecte ne cree aucune ligne et ne
    modifie aucun prix.

    Le `DISTINCT ON` traite le cas prevu par la specification : un meme
    `(station, carburant, maj)` vu deux fois avec des prix differents. On garde la
    derniere observation.
    """
    source = """
        SELECT DISTINCT ON (p.station_id, p.carburant, p.maj)
               p.station_id, p.carburant, p.prix, p.maj,
               p.collecte_id, c.debut AS vue_le
          FROM staging.prix p
          JOIN raw.collecte c ON c.id = p.collecte_id
          JOIN marts.dim_station d ON d.id = p.station_id
         WHERE p.collecte_id = %s
           AND p.prix IS NOT NULL
           AND p.maj IS NOT NULL
         ORDER BY p.station_id, p.carburant, p.maj, p.prix DESC
    """

    with connexion.cursor() as curseur:
        curseur.execute(
            f"""
            WITH source AS ({source})
            SELECT count(*)
              FROM source s
              JOIN marts.fact_prix f
                ON f.station_id = s.station_id
               AND f.carburant = s.carburant
               AND f.maj = s.maj
            """,
            (collecte_id,),
        )
        deja_connus = _compte(curseur.fetchone())

        curseur.execute(
            f"""
            WITH source AS ({source})
            INSERT INTO marts.fact_prix AS f
                (station_id, carburant, prix, maj,
                 premiere_collecte, derniere_observation)
            SELECT station_id, carburant, prix, maj, collecte_id, vue_le
              FROM source
            ON CONFLICT (station_id, carburant, maj) DO UPDATE SET
                   derniere_observation = EXCLUDED.derniere_observation
            """,
            (collecte_id,),
        )
        touches = curseur.rowcount

    return touches - deja_connus, deja_connus


def charger_ruptures(connexion: psycopg.Connection[tuple[object, ...]], collecte_id: int) -> int:
    """Remplace l'etat courant des ruptures par celui de la collecte.

    Une rupture qui disparait du flux doit disparaitre de la table : on supprime
    celles qui ne sont plus declarees plutot que de les laisser trainer.
    """
    with connexion.cursor() as curseur:
        curseur.execute(
            """
            INSERT INTO marts.rupture AS r
                (station_id, carburant, type, debut, derniere_vue)
            SELECT p.station_id, p.carburant, p.rupture_type, p.rupture_debut, c.debut
              FROM staging.prix p
              JOIN raw.collecte c ON c.id = p.collecte_id
              JOIN marts.dim_station d ON d.id = p.station_id
             WHERE p.collecte_id = %s AND p.rupture_type IS NOT NULL
            ON CONFLICT (station_id, carburant) DO UPDATE SET
                   type         = EXCLUDED.type,
                   debut        = EXCLUDED.debut,
                   derniere_vue = EXCLUDED.derniere_vue
            """,
            (collecte_id,),
        )
        inserees = curseur.rowcount
        curseur.execute(
            """
            DELETE FROM marts.rupture r
             WHERE NOT EXISTS (
                 SELECT 1 FROM staging.prix p
                  WHERE p.collecte_id = %s
                    AND p.station_id = r.station_id
                    AND p.carburant = r.carburant
                    AND p.rupture_type IS NOT NULL
             )
             AND EXISTS (
                 SELECT 1 FROM staging.station s
                  WHERE s.collecte_id = %s AND s.station_id = r.station_id
             )
            """,
            (collecte_id, collecte_id),
        )
    return inserees


# ---------------------------------------------------------------- orchestration


def charger(connexion: psycopg.Connection[tuple[object, ...]], collecte_id: int) -> ResultatMarts:
    """Charge une collecte de staging vers marts, en une seule transaction."""
    with connexion.transaction():
        partitions = assurer_partitions(connexion, mois_presents(connexion, collecte_id))
        inserees, majs = charger_stations(connexion, collecte_id)
        desactivees = marquer_absentes(connexion, collecte_id)
        nouveaux, revus = charger_prix(connexion, collecte_id)
        ruptures = charger_ruptures(connexion, collecte_id)

    journal.info(
        "marts : %d stations inserees, %d mises a jour, %d prix nouveaux, %d revus",
        inserees,
        majs,
        nouveaux,
        revus,
    )
    return ResultatMarts(
        stations_inserees=inserees,
        stations_mises_a_jour=majs,
        stations_desactivees=desactivees,
        prix_inseres=nouveaux,
        prix_revus=revus,
        ruptures=ruptures,
        partitions_creees=partitions,
    )
