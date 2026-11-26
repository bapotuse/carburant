"""Controles qualite, executes a chaque run.

Un controle est une question fermee posee en SQL, dont la reponse tient en deux
valeurs : un verdict et une mesure lisible. Le SQL vit ici plutot que dans une
migration parce que ces requetes sont des *questions*, pas des objets de la base :
elles changent avec notre comprehension des donnees, et on veut les relire a cote
du code qui les interprete.

Deux niveaux, et la distinction compte :

- **bloquant** : l'execution est marquee en echec et le processus sort en erreur.
  C'est ce qui declenchera l'alerte du Jalon 6. Reserve a ce qui signifie « la
  donnee servie est fausse » ou « la source a casse ».
- **avertissement** : consigne dans `meta.execution_etl`, visible dans le journal,
  mais l'execution reste un succes. Pour ce qui merite d'etre su sans justifier de
  reveiller quelqu'un.

Les donnees chargees ne sont jamais annulees par un controle en echec. Une collecte
ou le nombre de stations a bouge de 11 % reste une collecte valide a conserver :
c'est l'execution qu'on marque, pas la donnee qu'on jette.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg

journal = logging.getLogger("carburant.qualite")


@dataclass(frozen=True, slots=True)
class Controle:
    """Une question posee a la base, et ce qu'on fait de la reponse."""

    nom: str
    question: str
    sql: str
    """Doit renvoyer exactement une ligne : (ok boolean, mesure text)."""
    bloquant: bool = True


@dataclass(frozen=True, slots=True)
class Verdict:
    """La reponse a un controle."""

    nom: str
    question: str
    ok: bool
    mesure: str
    bloquant: bool

    def en_dictionnaire(self) -> dict[str, Any]:
        """Forme stockee dans `meta.execution_etl.avertissements`."""
        return {
            "controle": self.nom,
            "question": self.question,
            "ok": self.ok,
            "mesure": self.mesure,
            "bloquant": self.bloquant,
        }


# --------------------------------------------------------------------- stations
_STATIONS_STABLES: Final = """
WITH courant AS (
    SELECT count(*)::numeric AS n FROM marts.dim_station WHERE active
),
histoire AS (
    -- La moyenne des sept derniers jours, lue dans le journal des executions.
    -- `>= 3` executions : en dessous, il n'y a pas d'historique a comparer, et un
    -- controle qui echoue le premier jour n'apprend rien a personne.
    SELECT count(*)::int AS executions,
           avg((lignes_par_etape ->> 'stations_actives')::numeric) AS moyenne
      FROM meta.execution_etl
     WHERE statut = 'succes'
       AND debut >= now() - interval '7 days'
       AND lignes_par_etape ? 'stations_actives'
)
SELECT CASE
           WHEN histoire.executions < 3 THEN true
           WHEN histoire.moyenne IS NULL OR histoire.moyenne = 0 THEN true
           ELSE abs(courant.n - histoire.moyenne) <= 0.10 * histoire.moyenne
       END,
       CASE
           WHEN histoire.executions < 3
               THEN courant.n || ' stations actives (pas encore d historique : '
                    || histoire.executions || ' execution(s) sur sept jours)'
           ELSE courant.n || ' stations actives, moyenne sur sept jours '
                || round(histoire.moyenne, 1)
                || ' (ecart ' || round(100 * (courant.n - histoire.moyenne)
                                       / nullif(histoire.moyenne, 0), 1) || ' %)'
       END
  FROM courant, histoire
"""

# ------------------------------------------------------------------------ prix
_PRIX_DANS_LES_BORNES: Final = """
WITH hors AS (
    SELECT count(*)::int AS n
      FROM marts.prix_courant c
      JOIN marts.dim_carburant d ON d.code = c.carburant
     WHERE c.prix < d.borne_min OR c.prix > d.borne_max
)
SELECT n = 0,
       CASE WHEN n = 0 THEN 'aucun prix hors des bornes de son carburant'
            ELSE n || ' prix hors bornes' END
  FROM hors
"""

# Seuil volontairement large : la mesure du 23/11/2026 donne 0,4 a 2,5 % selon le
# carburant. A 5 %, le controle ne se declenche que si la regle ou la donnee a
# vraiment change de nature -- par exemple si le plancher de MAD disparaissait.
_PART_SUSPECTS_MAX: Final = 5.0

_PRIX_SUSPECTS: Final = f"""
WITH compte AS (
    SELECT count(*) FILTER (WHERE suspect)::numeric AS suspects,
           count(*)::numeric                        AS total
      FROM marts.prix_courant_qualifie
     WHERE fraicheur IN ('frais', 'recent')
       AND rupture_type IS NULL
)
SELECT total = 0 OR 100 * suspects / total <= {_PART_SUSPECTS_MAX},
       CASE WHEN total = 0 THEN 'aucun prix frais a juger'
            ELSE suspects || ' prix atypiques sur ' || total
                 || ' (' || round(100 * suspects / total, 2) || ' %, seuil {_PART_SUSPECTS_MAX} %)'
       END
  FROM compte
"""

# ----------------------------------------------------------------- coordonnees
# Emprise France metropolitaine + Corse. Le flux instantane ne contient aucune
# station en DROM (verifie le 23/11/2026 : 0 code postal en 97x/98x). Les archives
# annuelles, elles, en contiennent : l'amorcage filtre sur la meme emprise et
# compte ses rejets.
_EMPRISE: Final = "ST_MakeEnvelope(-5.3, 41.2, 9.7, 51.2, 4326)::geography"

_COORDONNEES_DANS_EMPRISE: Final = f"""
WITH hors AS (
    SELECT count(*)::int AS n
      FROM marts.dim_station
     WHERE active AND NOT ST_Intersects(geom, {_EMPRISE})
)
SELECT n = 0,
       CASE WHEN n = 0 THEN 'toutes les stations actives sont dans l emprise'
            ELSE n || ' station(s) hors de France metropolitaine et Corse' END
  FROM hors
"""

# ----------------------------------------------------------------- integrite
_PARTITION_DEFAUT_VIDE: Final = """
WITH orphelines AS (SELECT count(*)::int AS n FROM marts.fact_prix_defaut)
SELECT n = 0,
       CASE WHEN n = 0 THEN 'partition DEFAULT vide'
            ELSE n || ' ligne(s) dans la partition DEFAULT : une partition mensuelle manquait'
       END
  FROM orphelines
"""

# La cle primaire (station_id, carburant, maj) garantit deja l'unicite a l'interieur
# d'une partition. Entre partitions, PostgreSQL ne la garantit pas : une meme `maj`
# ne peut pourtant tomber que dans une seule partition, donc une violation ici
# signalerait des bornes de partition qui se chevauchent.
_GRAIN_UNIQUE: Final = """
WITH doublons AS (
    SELECT count(*)::int AS n
      FROM (SELECT station_id, carburant, maj
              FROM marts.fact_prix
             GROUP BY 1, 2, 3
            HAVING count(*) > 1
             LIMIT 100) d
)
SELECT n = 0,
       CASE WHEN n = 0 THEN 'grain unique : un seul prix par station, carburant et maj'
            ELSE n || ' couple(s) en double (bornes de partitions qui se chevauchent ?)'
       END
  FROM doublons
"""

# ----------------------------------------------------------------- fraicheur
# Le controle qui garde le piege du fuseau horaire. Les dates du flux sont en heure
# locale de Paris malgre un suffixe `+00:00` mensonger ; on les lit donc comme telles.
# Si la source passait un jour reellement en UTC, nos dates partiraient deux heures
# dans le futur en ete -- et c'est ici qu'on l'apprendrait.
_AUCUNE_DATE_FUTURE: Final = """
WITH futures AS (
    SELECT count(*)::int AS n, max(maj) AS plus_loin
      FROM marts.fact_prix
     WHERE maj > now() + interval '5 minutes'
)
SELECT n = 0,
       CASE WHEN n = 0 THEN 'aucune date de mise a jour dans le futur'
            ELSE n || ' prix date(s) du futur, jusqu a ' || plus_loin
                 || ' : le fuseau de la source a peut-etre change'
       END
  FROM futures
"""

_SOURCE_FRAICHE: Final = """
WITH derniere AS (SELECT max(maj) AS m FROM marts.fact_prix)
SELECT m IS NOT NULL AND m >= now() - interval '2 hours',
       CASE WHEN m IS NULL THEN 'aucun prix en base'
            ELSE 'changement de prix le plus recent : ' || m
                 || ' (il y a ' || date_trunc('minute', now() - m) || ')'
       END
  FROM derniere
"""

CONTROLES: Final[tuple[Controle, ...]] = (
    Controle(
        nom="stations_stables",
        question="Le nombre de stations est-il a moins de 10 % de la moyenne des 7 derniers jours ?",
        sql=_STATIONS_STABLES,
    ),
    Controle(
        nom="prix_dans_les_bornes",
        question="Tous les prix servis sont-ils dans les bornes de leur carburant ?",
        sql=_PRIX_DANS_LES_BORNES,
    ),
    Controle(
        nom="prix_suspects",
        question=f"La part de prix atypiques reste-t-elle sous {_PART_SUSPECTS_MAX} % ?",
        sql=_PRIX_SUSPECTS,
        # Avertissement : un prix atypique n'est pas un prix faux, et une vague de
        # hausses reelles peut faire monter la part sans que rien ne soit casse.
        bloquant=False,
    ),
    Controle(
        nom="coordonnees_dans_emprise",
        question="Toutes les stations actives sont-elles en France metropolitaine ou en Corse ?",
        sql=_COORDONNEES_DANS_EMPRISE,
    ),
    Controle(
        nom="partition_defaut_vide",
        question="La partition DEFAULT de fact_prix est-elle vide ?",
        sql=_PARTITION_DEFAUT_VIDE,
    ),
    Controle(
        nom="grain_unique",
        question="Le grain (station, carburant, maj) est-il unique ?",
        sql=_GRAIN_UNIQUE,
    ),
    Controle(
        nom="aucune_date_future",
        question="Aucune date de mise a jour n'est-elle dans le futur ?",
        sql=_AUCUNE_DATE_FUTURE,
    ),
    Controle(
        nom="source_fraiche",
        question="Le changement de prix le plus recent a-t-il moins de 2 heures ?",
        sql=_SOURCE_FRAICHE,
        # Avertissement : la source peut legitimement ne rien publier de neuf
        # pendant deux heures, une nuit calme par exemple. Ce qui doit alerter,
        # c'est l'absence de collecte -- et cela se lit dans meta.execution_etl.
        bloquant=False,
    ),
)


def executer(
    connexion: psycopg.Connection[tuple[object, ...]],
    controles: Sequence[Controle] = CONTROLES,
) -> list[Verdict]:
    """Pose chaque question a la base et renvoie les verdicts, dans l'ordre."""
    verdicts: list[Verdict] = []
    for controle in controles:
        with connexion.cursor() as curseur:
            curseur.execute(controle.sql)
            ligne = curseur.fetchone()
        if ligne is None or len(ligne) != 2:
            raise RuntimeError(
                f"controle {controle.nom} : attendu une ligne (ok, mesure), recu {ligne!r}"
            )
        ok, mesure = ligne
        if not isinstance(ok, bool):
            raise RuntimeError(f"controle {controle.nom} : verdict non booleen {ok!r}")
        verdict = Verdict(
            nom=controle.nom,
            question=controle.question,
            ok=ok,
            mesure=str(mesure),
            bloquant=controle.bloquant,
        )
        verdicts.append(verdict)
        if ok:
            journal.info("qualite %-26s ok   %s", controle.nom, verdict.mesure)
        elif controle.bloquant:
            journal.error("qualite %-26s ECHEC %s", controle.nom, verdict.mesure)
        else:
            journal.warning("qualite %-26s alerte %s", controle.nom, verdict.mesure)
    return verdicts


def echecs_bloquants(verdicts: Sequence[Verdict]) -> list[Verdict]:
    """Les verdicts qui doivent faire echouer l'execution."""
    return [v for v in verdicts if v.bloquant and not v.ok]


def resume(verdicts: Sequence[Verdict]) -> str:
    """Une ligne pour la sortie de `etl qualite`."""
    echecs = [v for v in verdicts if not v.ok]
    if not echecs:
        return f"{len(verdicts)} controles, tous au vert."
    bloquants = len([v for v in echecs if v.bloquant])
    return (
        f"{len(verdicts)} controles, {len(echecs)} en echec "
        f"dont {bloquants} bloquant(s) : {', '.join(v.nom for v in echecs)}."
    )
