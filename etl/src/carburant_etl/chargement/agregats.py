"""Agregats journaliers et rafraichissement des vues.

Ce que cette etape calcule, et pourquoi ce n'est pas ce qu'on croit.

Moyenner les prix **modifies** un jour donne biaise tout : les stations qui changent
souvent leurs prix pesent plus lourd que les autres, et les jours calmes ne sont
portes que par une poignee de stations nerveuses. On agrege donc les prix **en
vigueur** ce jour-la : pour chaque station et chaque carburant, le dernier
changement anterieur a la fin du jour, a condition qu'il ne soit pas perime.

Sont ecartes du calcul, mais comptes :

- les prix **perimes** (plus de 30 jours sans changement) : ils ne disent plus rien
  du prix pratique ;
- les carburants en **rupture** : la station ne le vend pas ce jour-la ;
- les prix **atypiques** au sens de `marts.est_suspect` : ce sont le plus souvent de
  vrais prix eleves (L'Ile-d'Yeu, Val-d'Isere), mais ils tirent une moyenne
  departementale sans rien dire du marche.

La mediane de reference et l'ecart median servant a juger l'atypie sont calcules
**sur le jour considere**, pas sur aujourd'hui : un agregat de 2019 se juge avec les
prix de 2019.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import psycopg

from carburant_etl.fuseau import PARIS

journal = logging.getLogger("carburant.agregats")

FENETRE_PEREMPTION_JOURS = 30
"""Au-dela, un prix sans changement ne temoigne plus de rien. Voir migration 004."""


@dataclass(frozen=True, slots=True)
class ResultatRefresh:
    """Ce qu'un rafraichissement a recalcule."""

    jours: int
    lignes_agregat: int
    reference_rafraichie: bool


# Les prix en vigueur a la fin d'un jour donne, qualifies et juges.
#
# `DISTINCT ON (station_id, carburant) ... ORDER BY maj DESC` : le dernier
# changement anterieur a la borne. La fenetre de 30 jours borne la lecture aux
# partitions utiles -- sans elle, la requete balaierait tout l'historique pour
# retrouver des prix de toute facon perimes.
_EN_VIGUEUR = """
WITH en_vigueur AS (
    SELECT DISTINCT ON (p.station_id, p.carburant)
           p.station_id, p.carburant, p.prix
      FROM marts.fact_prix p
     WHERE p.maj <  %(fin)s
       AND p.maj >= %(fin)s - make_interval(days => %(fenetre)s)
     ORDER BY p.station_id, p.carburant, p.maj DESC
),
vendus AS (
    SELECT e.station_id, e.carburant, e.prix, s.code_departement, s.autoroute
      FROM en_vigueur e
      JOIN marts.dim_station s ON s.id = e.station_id
     WHERE NOT EXISTS (
               SELECT 1 FROM marts.rupture r
                WHERE r.station_id = e.station_id AND r.carburant = e.carburant
           )
),
medianes AS (
    SELECT code_departement, carburant,
           count(*)::integer AS stations,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)::numeric AS mediane
      FROM vendus
     WHERE code_departement IS NOT NULL
     GROUP BY 1, 2
),
dispersion AS (
    SELECT m.code_departement, m.carburant, m.stations, m.mediane,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(v.prix - m.mediane))::numeric AS mad
      FROM medianes m
      JOIN vendus v ON v.code_departement = m.code_departement AND v.carburant = m.carburant
     GROUP BY 1, 2, 3, 4
),
juges AS (
    SELECT v.carburant, v.prix, v.code_departement, v.autoroute,
           marts.est_suspect(v.prix, d.mediane, d.mad, d.stations) AS suspect
      FROM vendus v
      LEFT JOIN dispersion d
             ON d.code_departement = v.code_departement AND d.carburant = v.carburant
)
"""

_AGREGER = (
    _EN_VIGUEUR
    + """
INSERT INTO marts.agregat_prix_jour
    (jour, carburant, dimension, valeur, stations, exclus,
     prix_min, prix_median, prix_moyen, prix_max, calcule_le)
SELECT * FROM (
    SELECT %(jour)s::date, carburant, 'france', '',
           count(*) FILTER (WHERE NOT suspect)::integer,
           count(*) FILTER (WHERE suspect)::integer,
           min(prix)    FILTER (WHERE NOT suspect),
           (percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)
                FILTER (WHERE NOT suspect))::numeric(5,3),
           round(avg(prix) FILTER (WHERE NOT suspect), 3),
           max(prix)    FILTER (WHERE NOT suspect),
           now()
      FROM juges
     GROUP BY carburant

    UNION ALL

    SELECT %(jour)s::date, carburant, 'departement', code_departement,
           count(*) FILTER (WHERE NOT suspect)::integer,
           count(*) FILTER (WHERE suspect)::integer,
           min(prix)    FILTER (WHERE NOT suspect),
           (percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)
                FILTER (WHERE NOT suspect))::numeric(5,3),
           round(avg(prix) FILTER (WHERE NOT suspect), 3),
           max(prix)    FILTER (WHERE NOT suspect),
           now()
      FROM juges
     WHERE code_departement IS NOT NULL
     GROUP BY carburant, code_departement

    UNION ALL

    SELECT %(jour)s::date, carburant, 'reseau',
           CASE WHEN autoroute THEN 'autoroute' ELSE 'route' END,
           count(*) FILTER (WHERE NOT suspect)::integer,
           count(*) FILTER (WHERE suspect)::integer,
           min(prix)    FILTER (WHERE NOT suspect),
           (percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)
                FILTER (WHERE NOT suspect))::numeric(5,3),
           round(avg(prix) FILTER (WHERE NOT suspect), 3),
           max(prix)    FILTER (WHERE NOT suspect),
           now()
      FROM juges
     GROUP BY carburant, autoroute
) lignes (jour, carburant, dimension, valeur, stations, exclus,
          prix_min, prix_median, prix_moyen, prix_max, calcule_le)
-- Un groupe entierement suspect n'a pas d'agregat : on ne publie pas une ligne
-- dont tous les prix ont ete ecartes.
WHERE stations > 0
ON CONFLICT (jour, carburant, dimension, valeur) DO UPDATE SET
    stations    = EXCLUDED.stations,
    exclus      = EXCLUDED.exclus,
    prix_min    = EXCLUDED.prix_min,
    prix_median = EXCLUDED.prix_median,
    prix_moyen  = EXCLUDED.prix_moyen,
    prix_max    = EXCLUDED.prix_max,
    calcule_le  = EXCLUDED.calcule_le
"""
)


def fin_du_jour(jour: dt.date) -> dt.datetime:
    """Le premier instant du lendemain, en heure de Paris.

    Les journees sont des journees francaises : le 3 mars finit a minuit heure de
    Paris, pas a minuit UTC. Une station qui change son prix a 23 h 30 le 3 mars le
    change bien le 3 mars.
    """
    lendemain = jour + dt.timedelta(days=1)
    return dt.datetime.combine(lendemain, dt.time.min, tzinfo=PARIS)


def rafraichir_reference(connexion: psycopg.Connection[tuple[object, ...]]) -> bool:
    """Recalcule la mediane et la MAD de chaque departement.

    `CONCURRENTLY` pour ne pas bloquer les lectures de l'API pendant le calcul. Il
    exige un index unique, et il echoue tant que la vue n'a jamais ete peuplee : au
    tout premier passage on fait donc un rafraichissement ordinaire.
    """
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            "SELECT relispopulated FROM pg_class WHERE oid = 'marts.reference_departementale'::regclass"
        )
        ligne = curseur.fetchone()
        peuplee = bool(ligne[0]) if ligne else False
        curseur.execute(
            "REFRESH MATERIALIZED VIEW CONCURRENTLY marts.reference_departementale"
            if peuplee
            else "REFRESH MATERIALIZED VIEW marts.reference_departementale"
        )
    journal.info("reference departementale rafraichie")
    return True


def jours_a_calculer(
    connexion: psycopg.Connection[tuple[object, ...]], *, limite: int | None = None
) -> list[dt.date]:
    """Les jours couverts par les donnees, du plus recent au plus ancien.

    Un jour est « couvert » des lors qu'un changement de prix lui est anterieur de
    moins de 30 jours : c'est la fenetre au-dela de laquelle un prix est perime.
    """
    with connexion.cursor() as curseur:
        curseur.execute(
            """
            SELECT min(maj)::date, max(maj)::date
              FROM marts.fact_prix
             WHERE maj <= now()
            """
        )
        ligne = curseur.fetchone()
    if ligne is None or ligne[0] is None:
        return []
    premier, dernier = ligne[0], ligne[1]
    if not isinstance(premier, dt.date) or not isinstance(dernier, dt.date):
        raise RuntimeError(f"plage de dates inattendue : {ligne!r}")
    aujourdhui = dt.datetime.now(tz=PARIS).date()
    dernier = min(dernier, aujourdhui)
    jours = [dernier - dt.timedelta(days=n) for n in range((dernier - premier).days + 1) if n >= 0]
    return jours[:limite] if limite is not None else jours


def calculer_agregats(
    connexion: psycopg.Connection[tuple[object, ...]], jours: list[dt.date]
) -> int:
    """Calcule (ou recalcule) les agregats des jours demandes. Idempotent."""
    total = 0
    for jour in jours:
        with connexion.transaction(), connexion.cursor() as curseur:
            curseur.execute(
                _AGREGER,
                {
                    "jour": jour,
                    "fin": fin_du_jour(jour),
                    "fenetre": FENETRE_PEREMPTION_JOURS,
                },
            )
            total += curseur.rowcount
    return total


def rafraichir(
    connexion: psycopg.Connection[tuple[object, ...]], *, jours: int | None = 7
) -> ResultatRefresh:
    """Rafraichit la reference puis recalcule les agregats des derniers jours.

    `jours` borne le recalcul aux N jours les plus recents : apres une collecte, les
    jours anterieurs n'ont pas bouge. `None` recalcule tout l'historique, ce que fait
    l'amorcage.
    """
    rafraichir_reference(connexion)
    a_calculer = jours_a_calculer(connexion, limite=jours)
    lignes = calculer_agregats(connexion, a_calculer)
    journal.info("agregats : %d jour(s), %d ligne(s)", len(a_calculer), lignes)
    return ResultatRefresh(jours=len(a_calculer), lignes_agregat=lignes, reference_rafraichie=True)


# --------------------------------------------------------------------- en masse
#
# Recalculer les agregats jour par jour convient apres une collecte -- un ou deux
# jours a refaire. Sur dix-neuf ans d'historique, c'est environ 7 000 requetes :
# intenable. Cette variante calcule une periode entiere en une passe.
#
# L'idee : au lieu de demander « quels prix etaient en vigueur le 3 mars ? » pour
# chaque jour, on demande a chaque changement de prix « pendant combien de jours
# as-tu ete en vigueur ? » et on le deplie. Un changement vaut jusqu'au suivant pour
# la meme station et le meme carburant -- c'est ce que donne `lead(...) OVER` -- et
# au plus trente jours, au-dela desquels le prix est perime.
_AGREGER_EN_MASSE = """
WITH bornes AS (
    SELECT %(debut)s::date AS premier, %(fin)s::date AS dernier
),
changements AS (
    SELECT p.station_id, p.carburant, p.prix,
           (p.maj AT TIME ZONE 'Europe/Paris')::date AS jour_debut,
           lead(p.maj) OVER (
               PARTITION BY p.station_id, p.carburant ORDER BY p.maj
           ) AS suivant
      FROM marts.fact_prix p, bornes b
     -- La fenetre de trente jours en amont ramene les prix encore en vigueur au
     -- premier jour demande, sans balayer tout l'historique.
     WHERE p.maj >= (b.premier - %(fenetre)s)::timestamptz
       AND p.maj <  (b.dernier + 1)::timestamptz
),
validites AS (
    SELECT c.station_id, c.carburant, c.prix,
           greatest(c.jour_debut, b.premier) AS du,
           least(
               coalesce((c.suivant AT TIME ZONE 'Europe/Paris')::date - 1,
                        c.jour_debut + %(fenetre)s),
               c.jour_debut + %(fenetre)s,
               b.dernier
           ) AS au
      FROM changements c, bornes b
),
en_vigueur AS (
    SELECT v.station_id, v.carburant, v.prix, j::date AS jour
      FROM validites v,
           LATERAL generate_series(v.du, v.au, interval '1 day') j
     WHERE v.au >= v.du
),
vendus AS (
    SELECT e.jour, e.carburant, e.prix, s.code_departement, s.autoroute
      FROM en_vigueur e
      JOIN marts.dim_station s ON s.id = e.station_id
     WHERE NOT EXISTS (
               SELECT 1 FROM marts.rupture r
                WHERE r.station_id = e.station_id AND r.carburant = e.carburant
           )
),
medianes AS (
    SELECT jour, code_departement, carburant,
           count(*)::integer AS stations,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)::numeric AS mediane
      FROM vendus
     WHERE code_departement IS NOT NULL
     GROUP BY 1, 2, 3
),
dispersion AS (
    SELECT m.jour, m.code_departement, m.carburant, m.stations, m.mediane,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(v.prix - m.mediane))::numeric AS mad
      FROM medianes m
      JOIN vendus v
        ON v.jour = m.jour
       AND v.code_departement = m.code_departement
       AND v.carburant = m.carburant
     GROUP BY 1, 2, 3, 4, 5
),
juges AS (
    SELECT v.jour, v.carburant, v.prix, v.code_departement, v.autoroute,
           marts.est_suspect(v.prix, d.mediane, d.mad, d.stations) AS suspect
      FROM vendus v
      LEFT JOIN dispersion d
        ON d.jour = v.jour
       AND d.code_departement = v.code_departement
       AND d.carburant = v.carburant
)
INSERT INTO marts.agregat_prix_jour
    (jour, carburant, dimension, valeur, stations, exclus,
     prix_min, prix_median, prix_moyen, prix_max, calcule_le)
SELECT * FROM (
    SELECT jour, carburant, 'france', '',
           count(*) FILTER (WHERE NOT suspect)::integer,
           count(*) FILTER (WHERE suspect)::integer,
           min(prix) FILTER (WHERE NOT suspect),
           (percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)
                FILTER (WHERE NOT suspect))::numeric(5,3),
           round(avg(prix) FILTER (WHERE NOT suspect), 3),
           max(prix) FILTER (WHERE NOT suspect),
           now()
      FROM juges GROUP BY jour, carburant
    UNION ALL
    SELECT jour, carburant, 'departement', code_departement,
           count(*) FILTER (WHERE NOT suspect)::integer,
           count(*) FILTER (WHERE suspect)::integer,
           min(prix) FILTER (WHERE NOT suspect),
           (percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)
                FILTER (WHERE NOT suspect))::numeric(5,3),
           round(avg(prix) FILTER (WHERE NOT suspect), 3),
           max(prix) FILTER (WHERE NOT suspect),
           now()
      FROM juges WHERE code_departement IS NOT NULL
     GROUP BY jour, carburant, code_departement
    UNION ALL
    SELECT jour, carburant, 'reseau',
           CASE WHEN autoroute THEN 'autoroute' ELSE 'route' END,
           count(*) FILTER (WHERE NOT suspect)::integer,
           count(*) FILTER (WHERE suspect)::integer,
           min(prix) FILTER (WHERE NOT suspect),
           (percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)
                FILTER (WHERE NOT suspect))::numeric(5,3),
           round(avg(prix) FILTER (WHERE NOT suspect), 3),
           max(prix) FILTER (WHERE NOT suspect),
           now()
      FROM juges GROUP BY jour, carburant, autoroute
) lignes (jour, carburant, dimension, valeur, stations, exclus,
          prix_min, prix_median, prix_moyen, prix_max, calcule_le)
WHERE stations > 0
ON CONFLICT (jour, carburant, dimension, valeur) DO UPDATE SET
    stations    = EXCLUDED.stations,
    exclus      = EXCLUDED.exclus,
    prix_min    = EXCLUDED.prix_min,
    prix_median = EXCLUDED.prix_median,
    prix_moyen  = EXCLUDED.prix_moyen,
    prix_max    = EXCLUDED.prix_max,
    calcule_le  = EXCLUDED.calcule_le
"""


def calculer_periode(
    connexion: psycopg.Connection[tuple[object, ...]],
    debut: dt.date,
    fin: dt.date,
) -> int:
    """Calcule les agregats de toute une periode en une passe.

    A utiliser apres un amorcage : `rafraichir` convient pour un ou deux jours, pas
    pour dix-neuf ans. Idempotent comme elle.
    """
    if fin < debut:
        raise ValueError(f"periode a l envers : {debut} -> {fin}")
    with connexion.transaction(), connexion.cursor() as curseur:
        curseur.execute(
            _AGREGER_EN_MASSE,
            {"debut": debut, "fin": fin, "fenetre": FENETRE_PEREMPTION_JOURS},
        )
        lignes = curseur.rowcount
    journal.info("agregats du %s au %s : %d ligne(s)", debut, fin, lignes)
    return lignes
